"""Tests for scoring.py — locks in behavior so future refactors can't silently
change the model. Run: python3 -m pytest test_scoring.py -q"""
import pandas as pd, numpy as np
from datetime import date
import scoring


def test_smash_tier_requires_exploit_pitcher():
    # MIXED pitcher never qualifies (matches the legend)
    assert scoring.smash_tier(90, "MIXED", 1.10, True) == ""
    # EXPLOIT+ with high score + favorable env = elite smash
    assert "ELITE SMASH" in scoring.smash_tier(90, "EXPLOIT+", 1.05, True)

def test_smash_tier_hostile_pitcher_blocks():
    assert scoring.smash_tier(90, "ELITE", 1.20, True) == ""
    assert scoring.smash_tier(90, "TOUGH", 1.20, True) == ""

def test_smash_tier_unconfirmed_lineup_blocks():
    assert scoring.smash_tier(90, "EXPLOIT", 1.05, False) == ""

def test_smash_tier_low_score_blocks():
    assert scoring.smash_tier(50, "EXPLOIT", 1.10, True) == ""

def test_hr_grade_tiers():
    assert scoring.hr_grade(25.0, 200) == "A+"
    assert scoring.hr_grade(3.0, 30) == "F"

def test_pitcher_grade_maps_correctly():
    # high test_score = tough/elite pitcher; low = exploitable
    assert scoring.pitcher_grade(90, sample_size=100) == "ELITE"
    assert scoring.pitcher_grade(30, sample_size=100) == "EXPLOIT+"

def test_dinger_score_percentile_ranks():
    df = pd.DataFrame({
        "pulled_brl_pct":[10,5,15], "avg_ev":[92,88,95], "barrel_pct":[12,6,18],
        "hard_hit":[45,35,55], "iso":[0.25,0.15,0.35], "blast_pct":[8,4,12],
    })
    ds = scoring.compute_dinger_score(df, context=False)
    # highest-power hitter (row 2) should score top
    assert ds.iloc[2] == ds.max()
    assert ds.iloc[1] == ds.min()

def test_dinger_weights_sum_stable():
    # reweight-02 generation — locked value
    assert abs(sum(scoring.DINGER_BASE_WEIGHTS.values()) - 10.0) < 1e-9

def test_smash_thresholds_locked():
    assert scoring.SMASH_ELITE_SCORE == 85
    assert scoring.SMASH_STRONG_SCORE == 75
    assert scoring.SMASH_BASE_SCORE == 65


# ── Phase 3: helpers.py tests ────────────────────────────────────────────────
import helpers

def test_metric_signal_bands():
    assert helpers.metric_signal("barrel_pct", 13) == ("🟢", "elite")
    assert helpers.metric_signal("barrel_pct", 3) == ("🔴", "below avg")
    assert helpers.metric_signal("barrel_pct", None) == ("", "")

def test_health_is_broken_flags_identical():
    # the anti-fake-split guard — "identical" L/R must read as broken
    assert helpers._health_is_broken("identical") is True
    assert helpers._health_is_broken("❌ error") is True
    assert helpers._health_is_broken("✅ working") is False

def test_verify_split_detects_fake():
    import pandas as pd
    # identical L/R columns = fake split → is_real False
    df = pd.DataFrame({"vl":[1.0,2.0,3.0], "vr":[1.0,2.0,3.0]})
    is_real, pct = helpers._verify_split(df, ["vl"], ["vr"])
    assert is_real is False
    # differing columns = real split → True
    df2 = pd.DataFrame({"vl":[1.0,2.0,3.0], "vr":[4.0,5.0,6.0]})
    is_real2, pct2 = helpers._verify_split(df2, ["vl"], ["vr"])
    assert is_real2 is True


# ── Phase 5: pipeline.py differential tests ──────────────────────────────────
import pipeline

def test_robbed_hr_cols_xhr_math():
    import pandas as pd, numpy as np
    df = pd.DataFrame({"barrel_pct":[12.0], "pa":[200], "home_run":[20]})
    out = pipeline._add_robbed_hr_cols(df)
    # xhr = 0.12 * 0.385 * 200 = 9.24
    assert abs(out.iloc[0]["xhr_neutral"] - 9.24) < 0.01
    assert abs(out.iloc[0]["hr_luck_gap"] - (9.24 - 20)) < 0.01

def test_robbed_hr_cols_missing_cols_safe():
    import pandas as pd
    # missing required columns → returns df unchanged (no crash)
    df = pd.DataFrame({"player_name":["A"]})
    out = pipeline._add_robbed_hr_cols(df)
    assert "xhr_neutral" not in out.columns
