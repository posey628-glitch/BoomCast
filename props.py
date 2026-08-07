"""Probability conversions. These are estimates, never betting recommendations."""
from __future__ import annotations

import pandas as pd

LEAGUE_HR_PER_PA = .030
BARREL_TO_XHR_PER_PA = .385


def hr_prob_per_pa(row: dict, park_factor: float = 1.0, pitcher_hr9: float | None = None) -> float | None:
    """Shrunk HR-per-PA estimate from observed HR rate and barrel rate."""
    pa = pd.to_numeric(pd.Series([row.get("pa")]), errors="coerce").iloc[0]
    hr = pd.to_numeric(pd.Series([row.get("home_run")]), errors="coerce").iloc[0]
    barrel = pd.to_numeric(pd.Series([row.get("barrel_pct")]), errors="coerce").iloc[0]
    if pd.isna(pa) or pa < 25 or pd.isna(hr):
        return None
    observed = (hr / pa * pa / (pa + 50)) + (LEAGUE_HR_PER_PA * 50 / (pa + 50))
    expected = barrel / 100 * BARREL_TO_XHR_PER_PA if pd.notna(barrel) else LEAGUE_HR_PER_PA
    observed_weight = min(.80, .30 + max(pa - 100, 0) / 500 * .50)
    rate = observed * observed_weight + expected * (1 - observed_weight)
    pitcher_factor = 1.0 if pitcher_hr9 is None or pd.isna(pitcher_hr9) else min(1.20, max(.80, float(pitcher_hr9) / 1.20))
    return float(min(.15, max(.003, rate * park_factor * pitcher_factor)))


def hr_prob_full_game(prob_per_pa: float | None, expected_pa: float = 4.2) -> float | None:
    if prob_per_pa is None or pd.isna(prob_per_pa):
        return None
    return float(1 - (1 - prob_per_pa) ** expected_pa)


def add_hr_probabilities(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    expected_pa = pd.to_numeric(out.get("lineup_pos", pd.Series(5, index=out.index)), errors="coerce").map(lambda spot: 4.65 - min(max((spot if pd.notna(spot) else 5) - 1, 0), 8) * .09)
    # env_boost includes the hand-aware park factor plus weather. Prefer it so
    # the stated game probability and visible environment column agree.
    rates = [hr_prob_per_pa(row, row.get("env_boost", row.get("park_factor", 1.0)), row.get("pitcher_hr9")) for row in out.to_dict("records")]
    out["model_hr_pa_pct"] = pd.Series(rates, index=out.index) * 100
    out["model_hr_game_pct"] = [hr_prob_full_game(rate, pa) * 100 if rate is not None else float("nan") for rate, pa in zip(rates, expected_pa)]
    return out
