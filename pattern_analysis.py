"""Small, honest summaries for locally graded snapshots."""
from __future__ import annotations
import pandas as pd

def feature_correlation(graded: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for column in ["hr_score", "hr_game_pct", "power_score", "sleeper_score"]:
        values = pd.to_numeric(graded.get(column), errors="coerce")
        outcome = pd.to_numeric(graded.get("homered"), errors="coerce")
        valid = values.notna() & outcome.notna()
        if valid.sum() >= 10 and values[valid].nunique() > 1 and outcome[valid].nunique() > 1:
            rows.append({"feature": column, "n": int(valid.sum()), "correlation": round(float(values[valid].corr(outcome[valid])), 3)})
    return pd.DataFrame(rows).sort_values("correlation", ascending=False) if rows else pd.DataFrame(columns=["feature", "n", "correlation"])

def calibration_summary(graded: pd.DataFrame) -> dict:
    played = graded.dropna(subset=["hr_game_pct", "homered"])
    if played.empty: return {}
    return {"n": len(played), "actual_hr_rate": round(float(played.homered.mean() * 100), 1), "brier_score": round(float(played.brier.mean()), 4)}
