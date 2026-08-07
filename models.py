"""Transparent, slate-level baseball scoring primitives for LaunchCast."""
from __future__ import annotations

import numpy as np
import pandas as pd


def _number(frame: pd.DataFrame, name: str) -> pd.Series:
    return pd.to_numeric(frame[name], errors="coerce") if name in frame else pd.Series(np.nan, index=frame.index)


def _linear(values: pd.Series, poor: float, elite: float) -> pd.Series:
    return ((values - poor) / (elite - poor) * 100).clip(0, 100)


def _weighted(frame: pd.DataFrame, parts: dict[str, tuple[pd.Series, float]], minimum: float = 0.0) -> pd.Series:
    """Average only present signals and require a minimum share of evidence."""
    total, available = pd.Series(0.0, index=frame.index), pd.Series(0.0, index=frame.index)
    max_weight = sum(weight for _, weight in parts.values())
    for values, weight in parts.values():
        present = values.notna()
        total += values.fillna(0) * weight
        available += present.astype(float) * weight
    result = total / available.replace(0, np.nan)
    return result.where(available >= max_weight * minimum)


def add_power_score(frame: pd.DataFrame) -> pd.DataFrame:
    """Absolute (not rank-based) raw-power score using published thresholds."""
    out = frame.copy()
    parts = {
        "barrel": (_linear(_number(out, "barrel_pct"), 4, 22), .25),
        "iso": (_linear(_number(out, "iso"), .10, .35), .22),
        "ev": (_linear(_number(out, "avg_ev"), 85, 95), .18),
        "hard_hit": (_linear(_number(out, "hard_hit"), 30, 60), .18),
        "fly_ball": (_linear(_number(out, "fb_pct"), 18, 50), .17),
    }
    out["power_score"] = _weighted(out, parts, minimum=.60).round(1)
    return out


def add_lift_score(frame: pd.DataFrame) -> pd.DataFrame:
    """Contact quality plus air-ball tendency; independent of raw power."""
    out = frame.copy()
    parts = {
        "hard_hit": (_linear(_number(out, "hard_hit"), 25, 55), .50),
        "fly_ball": (_linear(_number(out, "fb_pct"), 18, 50), .35),
        "barrel": (_linear(_number(out, "barrel_pct"), 4, 22), .15),
    }
    out["lift_score"] = _weighted(out, parts, minimum=.60).round(1)
    return out


def add_discipline_score(frame: pd.DataFrame) -> pd.DataFrame:
    """Lower strikeout rate is good; walk rate is a modest positive."""
    out = frame.copy()
    k_col = "k_pct" if "k_pct" in out else "k_percent"
    bb_col = "bb_pct" if "bb_pct" in out else "bb_percent"
    parts = {
        "strikeouts": (_linear(_number(out, k_col), 28, 14), .65),
        "walks": (_linear(_number(out, bb_col), 4, 14), .35),
    }
    out["discipline_score"] = _weighted(out, parts).round(1)
    return out


def enrich_slate(frame: pd.DataFrame) -> pd.DataFrame:
    """Add interpretable secondary scores without overwriting the app's model."""
    out = add_discipline_score(add_lift_score(add_power_score(frame)))
    # A matchup opportunity score deliberately separates pitcher/env context
    # from hitter talent; it is a useful explanation, not a second projection.
    pitcher = _linear(_number(out, "pitcher_hr9"), .70, 2.10)
    environment = _linear(_number(out, "env_boost"), .85, 1.18)
    out["matchup_score"] = _weighted(out, {
        "pitcher": (pitcher, .65), "environment": (environment, .35),
    }).round(1)
    # If an arsenal calculation was supplied, use it as a bounded additional
    # matchup lens; absent pitch data has no effect.
    pitch = _number(out, "pitch_match_score")
    out["matchup_score"] = out["matchup_score"].where(pitch.isna(), (out["matchup_score"].fillna(50) * .7 + pitch * .3).round(1))
    return out
