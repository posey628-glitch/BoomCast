"""Local, opt-in projection snapshots and outcome grading."""
from __future__ import annotations
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import pandas as pd

# Mount this directory in production (for example, -v launchcast-data:/data).
STORE = Path(os.environ.get("LAUNCHCAST_DATA_DIR", "work")) / "launchcast_snapshots.json"

def _read() -> list[dict]:
    try: return json.loads(STORE.read_text())
    except (FileNotFoundError, json.JSONDecodeError): return []

def _write(items: list[dict]) -> None:
    STORE.parent.mkdir(parents=True, exist_ok=True); STORE.write_text(json.dumps(items, indent=2, default=str))

def save_snapshot(slate_date: str, slate: pd.DataFrame) -> None:
    keep = [c for c in ["player_id", "player_name", "team", "game", "hr_score", "hr_game_pct", "power_score", "sleeper_score"] if c in slate]
    records = slate[keep].where(pd.notna(slate[keep]), None).to_dict("records")
    # One canonical saved board per slate date. A second click refreshes it
    # instead of contaminating the learning history with duplicates.
    items = [item for item in _read() if item.get("slate_date") != slate_date]
    items.append({"created_at": datetime.now(timezone.utc).isoformat(), "slate_date": slate_date, "hitters": records})
    _write(items[-60:])

def list_snapshots() -> list[dict]: return _read()

def grade_snapshot(index: int, outcomes: pd.DataFrame) -> pd.DataFrame:
    snapshot = _read()[index]; predicted = pd.DataFrame(snapshot["hitters"])
    actual = outcomes.copy(); actual.columns = [str(c).strip().lower() for c in actual.columns]
    key = "player_id" if "player_id" in predicted and "player_id" in actual else "player_name"
    if key not in actual or "hr" not in actual: raise ValueError("Outcome CSV needs hr and either player_id or player_name.")
    if key == "player_id":
        predicted[key] = pd.to_numeric(predicted[key], errors="coerce").astype("Int64")
        actual[key] = pd.to_numeric(actual[key], errors="coerce").astype("Int64")
    else:
        predicted[key] = predicted[key].astype(str).str.strip().str.casefold()
        actual[key] = actual[key].astype(str).str.strip().str.casefold()
    merged = predicted.merge(actual[[key, "hr"]], on=key, how="inner")
    merged["homered"] = pd.to_numeric(merged["hr"], errors="coerce").fillna(0).gt(0).astype(int)
    merged["brier"] = ((pd.to_numeric(merged.get("hr_game_pct"), errors="coerce") / 100) - merged["homered"]) ** 2
    return merged
