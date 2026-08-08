"""
pipeline.py — BoomCast near-pure data-pipeline transforms (Phase 5, careful).

These are inline functions lifted from app.py's main body that are genuinely
self-contained: they take a DataFrame, return a DataFrame, and capture NO
closure state from the surrounding flow. UNLIKE Phases 1-4 (verbatim moves),
Phase 5 functions are verified by DIFFERENTIAL TESTING — running the extracted
version against saved inputs to confirm identical output — because dedenting +
module-scoping is a small rewrite, not a byte move.

Only near-pure transforms live here. The deeply closure-coupled parts of the
main body (that read/write dozens of shared locals) are LEFT in app.py by
design — extracting them safely needs live testing, not mock verification.
"""
import pandas as pd
import numpy as np


def _add_robbed_hr_cols(m_df):
    try:
        if (m_df is None or m_df.empty
            or "barrel_pct" not in m_df.columns
            or "pa" not in m_df.columns
            or "home_run" not in m_df.columns):
            return m_df
        _b = pd.to_numeric(m_df["barrel_pct"], errors="coerce")
        _p = pd.to_numeric(m_df["pa"], errors="coerce")
        _h = pd.to_numeric(m_df["home_run"], errors="coerce")
        # v43.19 (reviewer-validated, REVERTS v43.18 change which was
        # wrong): use BARREL_TO_XHR_PER_PA from props.py — single source
        # of truth, same value used by hr_prob_per_pa. The v43.18
        # changelog claimed 0.385 was "barrels per BBE × PA = double
        # counted" — but 0.385 in props.py was DERIVED from 0.70 (BBE/PA)
        # × 0.55 (HR/barrel), meaning it ALREADY includes the BBE/PA
        # correction. So multiplying by PA is correct: xHR = barrel_pct
        # × CONSTANT × PA gives full-season xHR. The v43.18 0.25 change
        # caused xhr_neutral to UNDER-count by ~35% (luck gaps showed
        # hitters as luckier than they actually were).
        try:
            from props import BARREL_TO_XHR_PER_PA
        except ImportError:
            BARREL_TO_XHR_PER_PA = 0.385
        m_df["xhr_neutral"] = ((_b / 100.0) * BARREL_TO_XHR_PER_PA * _p).round(2)
        m_df["hr_luck_gap"] = (m_df["xhr_neutral"] - _h).round(2)
        _den = m_df["xhr_neutral"].replace(0, np.nan)
        m_df["hr_conv_ratio"] = (_h / _den).round(2)
    except Exception:
        pass
    return m_df
