"""
helpers.py — BoomCast pure display/validation helpers.

Extracted verbatim from app.py (mlb-hr-and-k v46.54). Metric band lookups,
split-realness verification, health-status checks, and schema validation.
All stateless — no Streamlit, no network. Phase 3 of the modular rebuild.
"""
import pandas as pd
import numpy as np


# ── Metric bands (thresholds -> emoji/label) + cell tint colors ──────────────
_COMPOSITE_BANDS = [(80, "🟢", "elite"), (60, "🟡", "strong"),
                    (40, "🟠", "middling"), (float("-inf"), "🔴", "weak")]
METRIC_BANDS = {
    # raw skills (league-anchored)
    "barrel_pct":     [(12, "🟢", "elite"), (8, "🟡", "strong"), (5, "🟠", "average"), (float("-inf"), "🔴", "below avg")],
    "pulled_brl_pct": [(9, "🟢", "elite"), (6, "🟡", "strong"), (3.5, "🟠", "average"), (float("-inf"), "🔴", "below avg")],
    "pull_air_pct":   [(25, "🟢", "elite"), (20, "🟡", "strong"), (15, "🟠", "average"), (float("-inf"), "🔴", "low")],
    "ctx_lift_pp":    [(5, "🟢", "big lift"), (2.5, "🟡", "lift"), (0, "🟠", "neutral"), (float("-inf"), "🔴", "tougher than usual")],
    "avg_ev":         [(91.5, "🟢", "elite"), (89.5, "🟡", "strong"), (87.5, "🟠", "average"), (float("-inf"), "🔴", "soft")],
    "hard_hit":       [(48, "🟢", "elite"), (42, "🟡", "strong"), (37, "🟠", "average"), (float("-inf"), "🔴", "below avg")],
    "iso":            [(0.240, "🟢", "elite power"), (0.180, "🟡", "strong"), (0.140, "🟠", "average"), (float("-inf"), "🔴", "light")],
    "xslg":           [(0.520, "🟢", "elite"), (0.450, "🟡", "strong"), (0.400, "🟠", "average"), (float("-inf"), "🔴", "weak")],
    "xwoba":          [(0.370, "🟢", "elite"), (0.340, "🟡", "strong"), (0.315, "🟠", "average"), (float("-inf"), "🔴", "weak")],
    "blast_pct":      [(15, "🟢", "elite (approx bands)"), (9, "🟡", "strong"), (5, "🟠", "average"), (float("-inf"), "🔴", "low")],
    "sweet_spot_pct": [(38, "🟢", "elite"), (34, "🟡", "strong"), (30, "🟠", "average"), (float("-inf"), "🔴", "low")],
    "hr_game_pct":    [(21, "🟢", "A-range probability"), (13, "🟡", "B-range"), (7, "🟠", "C-range"), (float("-inf"), "🔴", "long shot")],
    # our 0-100 composite family — uniform percentile bands
    "dinger_score": _COMPOSITE_BANDS, "power_composite": _COMPOSITE_BANDS,
    "lift_score": _COMPOSITE_BANDS, "power_score": _COMPOSITE_BANDS,
    "discipline_score": _COMPOSITE_BANDS, "pitch_match_score": _COMPOSITE_BANDS,
    "pitch_hr_score": _COMPOSITE_BANDS, "matchup_opp": _COMPOSITE_BANDS,
    "barrel_matchup_score": _COMPOSITE_BANDS, "two_way_matchup_score": _COMPOSITE_BANDS,
    "sleeper_score": _COMPOSITE_BANDS,
}
# v45.38 (user: shades too close to tell apart): stronger alphas, more
# separated hues, and a colored left edge per band so tiers read instantly
# even for close hues.

_BAND_TINT = {
    "🟢": "background-color: rgba(0, 230, 118, 0.32); box-shadow: inset 3px 0 0 #00E676",
    "🟡": "background-color: rgba(255, 214, 0, 0.30); box-shadow: inset 3px 0 0 #FFD600",
    "🟠": "background-color: rgba(255, 109, 0, 0.30); box-shadow: inset 3px 0 0 #FF6D00",
    "🔴": "background-color: rgba(213, 0, 0, 0.28); box-shadow: inset 3px 0 0 #FF1744",
}


# ────────────────────────────────────────────────────────────────────────────
def metric_signal(metric, value):
    """(emoji, label) verdict for a metric value per METRIC_BANDS; ("", "") if
    unbanded or missing."""
    bands = METRIC_BANDS.get(metric)
    if bands is None or value is None:
        return "", ""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "", ""
    if pd.isna(v):
        return "", ""
    for thr, emo, lab in bands:
        if v >= thr:
            return emo, lab
    return "", ""

# ────────────────────────────────────────────────────────────────────────────
def _band_cell_style(metric):
    """Styler function factory: subtle background tint per band (NaN → none)."""
    def _f(v):
        emo, _ = metric_signal(metric, v)
        return _BAND_TINT.get(emo, "")
    return _f

# ────────────────────────────────────────────────────────────────────────────
def _verify_split(df, left_cols, right_cols, min_diff_frac: float = 0.10):
    """v45.92: reusable split-realness check. The recurring bug this session
    (pitcher arsenal AND hitter split both silently served identical L/R data)
    shares one root cause: code trusted "both sides returned rows" as proof of
    a real split. This helper PROVES it — returns (is_real, pct_differ):
      True  -> >min_diff_frac of rows differ between L and R (real split)
      False -> L and R identical (fake split — the bug)
      None  -> can't tell (missing columns / no overlapping data)
    """
    try:
        pairs = list(zip(left_cols, right_cols))
        have = [(l, r) for l, r in pairs
                if df is not None and not df.empty
                and l in df.columns and r in df.columns]
        if not have:
            return (None, 0.0)
        max_diff = 0.0
        saw_data = False
        for lc, rc in have:
            both = df[[lc, rc]].dropna()
            if len(both) > 0:
                saw_data = True
                max_diff = max(max_diff, float((both[lc] != both[rc]).mean()))
        if not saw_data:
            return (None, 0.0)
        return (max_diff > min_diff_frac, max_diff * 100.0)
    except Exception:
        return (None, 0.0)


# v45.92: central registry — classifies each source SCORING-critical (breakage
# corrupts rankings, banner loudly) vs DISPLAY (cosmetic, degrade quietly).
_HEALTH_SOURCE_TIERS = {
    "_hitter_api_split_status_display":  ("Hitter L/R split",       "scoring"),
    "_arsenal_split_status":             ("Pitcher arsenal split",  "scoring"),
    "_hand_statcast_status_display":     ("Hitter statcast split (legacy)", "display"),
    "_bat_tracking_status_display":      ("Bat tracking",           "scoring"),
    "_weather_status_display":           ("Weather",                "display"),
    "_zone_fetch_status_display":        ("Zone/plate-discipline",  "display"),
    "_hot_zone_status_display":          ("Hot/cold zones (statsapi)", "display"),
    "_saber_status_display":             ("wRC+ / expected stats (statsapi)", "display"),
    "_hist_priors_status_display":       ("3-yr historical priors (tracked-only)", "display"),
    "_hist_splits_status_display":       ("3-yr historical splits — platoon/day-night/month", "display"),
    "_spray_status_display":             ("Spray pull-side (statsapi)", "display"),
    "_p_xstats_status_display":          ("Pitcher xSLG-allowed (statsapi)", "display"),
    "_scmetric_status_display":          ("Statcast metrics EV/LA (statsapi)", "display"),
    "_savant_drift_status":              ("Savant column drift (Savant)", "scoring"),
}

# ────────────────────────────────────────────────────────────────────────────
def _health_is_broken(status_str: str) -> bool:
    """BROKEN if the status contains a failure keyword. Mirrors the Data Health
    Summary icon logic so the banner and summary always agree."""
    s = str(status_str).lower()
    return ("broken" in s or "unavailable" in s or "error" in s
            or "failed" in s or "dead" in s or "identical" in s
            or "❌" in str(status_str))

# ────────────────────────────────────────────────────────────────────────────
def validate_slate_schema(df, tracked_cols=None) -> list:
    """v46.09 (review-suggested): sanity-check the final combined slate before
    snapshot, catching the SILENT failure classes we keep hitting:
      - critical columns missing (broken merge/rename)
      - a tracked column present but ALL-NaN (fetch worked, join dropped it —
        the 'high in fetch, 0% in combined' bug that stranded p_x_slg_allowed)
      - impossible values (barrel>60, EV out of range) = a parse/unit bug tell
        (exactly how the IP notation bug would surface)
    Returns a list of issue strings (empty=clean). Non-fatal — surfaced to
    Pipeline Health so problems are VISIBLE, not silently corrupting rankings.
    """
    issues = []
    if df is None or not hasattr(df, "columns"):
        return ["combined slate is None or not a DataFrame"]
    if df.empty:
        return ["combined slate is EMPTY (0 rows)"]
    for col in ("player_id", "pick_score", "hr_score"):
        if col not in df.columns:
            issues.append(f"MISSING critical column: {col}")
    if "player_id" in df.columns:
        _pid_null = int(df["player_id"].isna().sum())
        if _pid_null > 0:
            issues.append(f"{_pid_null} row(s) with NULL player_id")
    _range_checks = {
        "barrel_pct": (0, 60), "hard_hit": (0, 100), "avg_ev": (50, 130),
        "iso": (0, 1.0), "hr_game_pct": (0, 100), "pick_score": (0, 120),
        "hr9": (0, 10), "era": (0, 30),
    }
    for col, (lo, hi) in _range_checks.items():
        if col in df.columns:
            _num = pd.to_numeric(df[col], errors="coerce")
            _bad = int(((_num < lo) | (_num > hi)).sum())
            if _bad > 0:
                issues.append(f"{col}: {_bad} value(s) outside [{lo},{hi}] (max={_num.max()})")
    if tracked_cols:
        for col in tracked_cols:
            if col in df.columns and df[col].notna().sum() == 0:
                issues.append(f"{col}: present but ALL-NaN (join likely dropped it)")
    return issues
