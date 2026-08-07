"""Derived predictive scores and player enrichment."""
from __future__ import annotations

import numpy as np
import pandas as pd


def _safe_pct(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").fillna(0)


def enrich_slate(frame: pd.DataFrame) -> pd.DataFrame:
    """Add derived power, lift, matchup, and discipline scores."""
    out = frame.copy()

    # Power score: barrel% + hard_hit + iso + exit velo
    power_components = pd.DataFrame({
        "barrel": _safe_pct(out.get("barrel_pct")),
        "hard_hit": _safe_pct(out.get("hard_hit")),
        "iso": _safe_pct(out.get("iso")) * 100,  # scale ISO to ~0-40 range
        "avg_ev": (_safe_pct(out.get("avg_ev")) - 80).clip(0, 20),  # reward EV above 80
    })
    out["power_score"] = power_components.mean(axis=1).round(1)

    # Lift score: flyball% + iso (both drive elevation)
    lift_components = pd.DataFrame({
        "fb_pct": _safe_pct(out.get("fb_pct")),
        "iso": _safe_pct(out.get("iso")) * 100,
    })
    out["lift_score"] = lift_components.mean(axis=1).round(1)

    # Matchup score: pitcher HR/9 (higher = better for hitter) + platoon advantage
    pitcher_hr9 = _safe_pct(out.get("pitcher_hr9"))
    # Platoon: batter gets advantage if opposite hand of pitcher
    bats = out.get("bats", pd.Series("R", index=out.index)).astype(str).str.upper()
    p_hand = out.get("pitcher_hand", pd.Series("R", index=out.index)).astype(str).str.upper()
    platoon = ((bats == "L") & (p_hand == "R")) | ((bats == "R") & (p_hand == "L"))
    platoon_bonus = platoon.astype(float) * 5  # 5-point platoon bonus
    out["matchup_score"] = (pitcher_hr9 * 15 + platoon_bonus).round(1)

    # Discipline score: implied by power + lineup position (earlier = more PAs)
    lineup = pd.to_numeric(out.get("lineup_pos"), errors="coerce").fillna(5)
    pa_bonus = (10 - lineup).clip(0, 9) * 2  # earlier lineup = more PAs
    out["discipline_score"] = (pa_bonus + _safe_pct(out.get("barrel_pct")) * 0.5).round(1)

    # Form score: recent HR trend
    recent = pd.to_numeric(out.get("recent_hr"), errors="coerce").fillna(0)
    out["form_score"] = (recent * 8).round(1)

    # Composite predictive score (independent of the main hr_score)
    out["predictive_score"] = (
        out["power_score"].fillna(0) * 0.35 +
        out["lift_score"].fillna(0) * 0.25 +
        out["matchup_score"].fillna(0) * 0.20 +
        out["form_score"].fillna(0) * 0.10 +
        out["discipline_score"].fillna(0) * 0.10
    ).round(1)

    return out
