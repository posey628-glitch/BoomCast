"""Honest summaries for locally graded snapshots."""
from __future__ import annotations

import numpy as np
import pandas as pd


def feature_correlation(graded: pd.DataFrame) -> pd.DataFrame:
    """Correlate each feature with actual home-run outcomes."""
    rows = []
    features = ["hr_score", "hr_game_pct", "power_score", "lift_score", "matchup_score", 
                "discipline_score", "form_score", "predictive_score", "barrel_pct", 
                "hard_hit", "iso", "avg_ev", "fb_pct", "pitcher_hr9", "env_boost"]
    outcome = pd.to_numeric(graded.get("homered"), errors="coerce")
    for col in features:
        if col not in graded.columns:
            continue
        values = pd.to_numeric(graded[col], errors="coerce")
        valid = values.notna() & outcome.notna()
        if valid.sum() >= 8 and values[valid].nunique() > 1 and outcome[valid].nunique() > 1:
            corr = values[valid].corr(outcome[valid])
            rows.append({
                "feature": col,
                "n": int(valid.sum()),
                "correlation": round(float(corr), 3),
                "mean_when_hr": round(float(values[valid & (outcome == 1)].mean()), 2) if (valid & (outcome == 1)).any() else None,
                "mean_when_no_hr": round(float(values[valid & (outcome == 0)].mean()), 2) if (valid & (outcome == 0)).any() else None,
            })
    df = pd.DataFrame(rows).sort_values("correlation", ascending=False)
    return df if not df.empty else pd.DataFrame(columns=["feature", "n", "correlation", "mean_when_hr", "mean_when_no_hr"])


def calibration_summary(graded: pd.DataFrame) -> dict | None:
    """Overall calibration metrics."""
    played = graded.dropna(subset=["hr_game_pct", "homered"])
    if played.empty:
        return None
    prob = played["hr_game_pct"] / 100.0
    brier = float((prob - played["homered"]) ** 2).mean()
    return {
        "n": len(played),
        "actual_hr_rate": round(float(played["homered"].mean() * 100), 1),
        "brier_score": round(brier, 4),
        "avg_predicted_prob": round(float(prob.mean() * 100), 1),
        "calibration_error": round(abs(float(prob.mean() * 100) - float(played["homered"].mean() * 100)), 1),
    }


def tier_performance(graded: pd.DataFrame) -> pd.DataFrame:
    """How did each grade tier perform?"""
    if "grade" not in graded.columns or "homered" not in graded.columns:
        return pd.DataFrame()
    tiers = graded.groupby("grade").agg(
        n=("homered", "count"),
        actual_hr_rate=("homered", "mean"),
        avg_predicted=("hr_game_pct", "mean"),
        avg_score=("hr_score", "mean"),
    ).reset_index()
    tiers["actual_hr_rate"] = (tiers["actual_hr_rate"] * 100).round(1)
    tiers["avg_predicted"] = tiers["avg_predicted"].round(1)
    tiers["avg_score"] = tiers["avg_score"].round(1)
    tiers["calibration_gap"] = (tiers["avg_predicted"] - tiers["actual_hr_rate"]).round(1)
    return tiers.sort_values("avg_score", ascending=False)


def feature_importance(graded: pd.DataFrame) -> pd.DataFrame:
    """Rank features by how well they separate HR vs no-HR."""
    rows = []
    features = ["power_score", "lift_score", "matchup_score", "discipline_score", 
                "form_score", "barrel_pct", "hard_hit", "iso", "avg_ev", "fb_pct", 
                "pitcher_hr9", "env_boost"]
    outcome = pd.to_numeric(graded.get("homered"), errors="coerce")
    for col in features:
        if col not in graded.columns:
            continue
        vals = pd.to_numeric(graded[col], errors="coerce")
        valid = vals.notna() & outcome.notna()
        if valid.sum() < 10:
            continue
        hr_vals = vals[valid & (outcome == 1)]
        no_vals = vals[valid & (outcome == 0)]
        if len(hr_vals) < 3 or len(no_vals) < 3:
            continue
        # Effect size (Cohen's d)
        pooled_std = np.sqrt(((len(hr_vals)-1)*hr_vals.var() + (len(no_vals)-1)*no_vals.var()) / (len(hr_vals)+len(no_vals)-2))
        cohens_d = abs((hr_vals.mean() - no_vals.mean()) / pooled_std) if pooled_std > 0 else 0
        rows.append({
            "feature": col,
            "cohens_d": round(float(cohens_d), 3),
            "hr_mean": round(float(hr_vals.mean()), 2),
            "no_hr_mean": round(float(no_vals.mean()), 2),
            "n_hr": len(hr_vals),
            "n_no_hr": len(no_vals),
        })
    df = pd.DataFrame(rows).sort_values("cohens_d", ascending=False)
    return df if not df.empty else pd.DataFrame(columns=["feature", "cohens_d", "hr_mean", "no_hr_mean", "n_hr", "n_no_hr"])
