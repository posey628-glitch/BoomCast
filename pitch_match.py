"""Pitch-arsenal matchup calculation, usable whenever arsenal data is supplied."""
from __future__ import annotations
import numpy as np
import pandas as pd

def pitch_match_score(pitcher_arsenal: pd.DataFrame, hitter_arsenal: pd.DataFrame) -> dict:
    """Weight hitter per-pitch production by the opposing pitcher's actual usage."""
    if pitcher_arsenal is None or hitter_arsenal is None or pitcher_arsenal.empty or hitter_arsenal.empty:
        return {"pitch_match_score": None, "pitch_hr_score": None, "coverage": 0.0}
    p_name = "pitch_name" if "pitch_name" in pitcher_arsenal else "pitch_type"
    h_name = "pitch_name" if "pitch_name" in hitter_arsenal else "pitch_type"
    usage = "pitch_usage" if "pitch_usage" in pitcher_arsenal else "usage"
    if any(col not in pitcher_arsenal for col in (p_name, usage)) or h_name not in hitter_arsenal:
        return {"pitch_match_score": None, "pitch_hr_score": None, "coverage": 0.0}
    hitter = hitter_arsenal.drop_duplicates(h_name).set_index(h_name)
    total_usage = weighted_woba = weighted_slg = matched = 0.0
    for row in pitcher_arsenal.to_dict("records"):
        pitch, share = row.get(p_name), pd.to_numeric(pd.Series([row.get(usage)]), errors="coerce").iloc[0]
        if pd.isna(share) or share <= 0 or pitch not in hitter.index: continue
        stats = hitter.loc[pitch]
        woba = pd.to_numeric(pd.Series([stats.get("est_woba", stats.get("xwoba"))]), errors="coerce").iloc[0]
        slg = pd.to_numeric(pd.Series([stats.get("slg")]), errors="coerce").iloc[0]
        if pd.notna(woba): weighted_woba += float(woba) * share; total_usage += share; matched += share
        if pd.notna(slg): weighted_slg += float(slg) * share
    if not total_usage: return {"pitch_match_score": None, "pitch_hr_score": None, "coverage": 0.0}
    avg_woba, avg_slg = weighted_woba / total_usage, weighted_slg / total_usage
    return {"pitch_match_score": round(float(np.clip((avg_woba - .250) / .180 * 100, 0, 100)), 1), "pitch_hr_score": round(float(np.clip((avg_slg - .300) / .450 * 100, 0, 100)), 1), "coverage": round(float(matched / pitcher_arsenal[usage].sum() * 100), 1)}
