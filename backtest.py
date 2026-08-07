"""Local snapshot storage and grading for the Learning tab."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

WORK_DIR = Path(os.environ.get("LAUNCHCAST_DATA_DIR", "work"))
WORK_DIR.mkdir(parents=True, exist_ok=True)


def _snapshot_path(index: int) -> Path:
    return WORK_DIR / f"snapshot_{index:04d}.json"


def save_snapshot(slate_date: str, scored: pd.DataFrame) -> None:
    """Serialize the current scored slate to a local JSON file."""
    records = scored.copy()
    # Convert non-serializable types
    for col in records.columns:
        if records[col].dtype.name == "category":
            records[col] = records[col].astype(str)
        elif pd.api.types.is_datetime64_any_dtype(records[col]):
            records[col] = records[col].astype(str)
    payload = {
        "slate_date": slate_date,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "data": records.to_dict("records"),
    }
    existing = list_snapshots()
    path = _snapshot_path(len(existing))
    with open(path, "w") as f:
        json.dump(payload, f)


def list_snapshots() -> list[dict]:
    """Return metadata for every saved snapshot."""
    snaps = []
    for i in range(9999):
        path = _snapshot_path(i)
        if not path.exists():
            break
        with open(path) as f:
            data = json.load(f)
        snaps.append({"slate_date": data["slate_date"], "created_at": data["created_at"]})
    return snaps


def grade_snapshot(snapshot_index: int, outcomes: pd.DataFrame) -> pd.DataFrame:
    """Merge a saved snapshot with an outcomes CSV and compute Brier scores."""
    path = _snapshot_path(snapshot_index)
    with open(path) as f:
        payload = json.load(f)
    proj = pd.DataFrame(payload["data"])

    # Normalize outcomes
    outcomes = outcomes.copy()
    id_col = None
    for candidate in ["player_id", "player_name"]:
        if candidate in outcomes.columns:
            id_col = candidate
            break
    if id_col is None:
        raise ValueError("Outcomes CSV must contain 'player_id' or 'player_name'")

    outcomes["homered"] = pd.to_numeric(outcomes.get("hr", outcomes.get("homered", 0)), errors="coerce").fillna(0).clip(0, 1)

    # Merge
    merge_on = id_col if id_col in proj.columns else "player_name"
    if merge_on not in proj.columns:
        raise ValueError(f"Snapshot missing merge key: {merge_on}")
    graded = proj.merge(outcomes[[id_col, "homered"]], left_on=merge_on, right_on=id_col, how="left")
    graded["homered"] = graded["homered"].fillna(0)

    # Brier score for hr_game_pct (probability in percent -> decimal)
    prob = pd.to_numeric(graded.get("hr_game_pct"), errors="coerce").fillna(0) / 100.0
    graded["brier"] = (prob - graded["homered"]) ** 2
    return graded
