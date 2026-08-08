"""
scoring.py — BoomCast pure scoring & grading functions.

Extracted VERBATIM from the monolithic app.py (mlb-hr-and-k v46.54) as Phase 1
of the BoomCast modular rebuild. These functions are STATELESS: they take
DataFrames / scalars and return scores, grades, and labels. No Streamlit, no
network, no global mutation — which is exactly why they were safe to lift out
first and why they're independently testable.

Behavior is intended to be BYTE-IDENTICAL to the original app.py. Do not change
the math here without evidence (FDR-gated, validated on graded slates) — this is
the model that has shown a real edge.
"""
import pandas as pd
import numpy as np
from datetime import date


# ── Smash-tier thresholds (canonical; referenced by smash_tier + captions) ────
SMASH_ELITE_SCORE = 85      # HR Score ≥ this for ELITE tier
SMASH_STRONG_SCORE = 75     # HR Score ≥ this for STRONG
SMASH_BASE_SCORE = 65       # HR Score ≥ this for base SMASH
SMASH_ENV_FAVORABLE = 1.00  # env_boost ≥ this = actively helps (ELITE gate)
SMASH_ENV_NEUTRAL = 0.92    # env_boost ≥ this = non-hostile (STRONG/SMASH gate)


# ── Dinger (power-score) weights + context multipliers ───────────────────────
DINGER_BASE_WEIGHTS = {
    # v46.34 reweight-02 (½-step, FDR-guarded evidence): shift from barrel-family
    # toward iso + hard_hit. iso was the largest, most stable mover (top-5
    # predictor over 25 slates, survives FDR); avg_ev eased from #1 but still
    # leads. ½-step = half the distance current→proposed, so it self-corrects if
    # the signal partly reverts (next cycle re-derives from fresh data).
    "pulled_brl_pct": 1.694,  # reweight-01 1.758 → ½-step toward 1.63
    "avg_ev": 2.019,          # 2.058 → ½-step toward 1.98 (still the top weight)
    "barrel_pct": 1.674,      # 1.748 → ½-step toward 1.60
    "hard_hit": 1.714,        # 1.618 → ½-step toward 1.81 (contact quality UP)
    "iso": 1.679,             # 1.529 → ½-step toward 1.83 (biggest mover, UP)
    "blast_pct": 1.220,       # 1.289 → ½-step toward 1.15 (least-observed)
}
# Context multipliers: each maps a per-slate signal to a gentle multiplier
# on the base. Kept modest (max ~±20% each) so context TILTS the power
# ranking toward tonight's spot without letting a good matchup crown a
# weak-power hitter. Capped in aggregate to [0.70, 1.35].
DINGER_CONTEXT = {
    "recency": 0.20,   # recent HR/ISO form
    "env": 0.15,       # park + weather (env_boost)
    "matchup": 0.15,   # vs tonight's pitcher (matchup_opp)
}
# (v45.15: removed the dead DINGER_SCORE_WEIGHTS alias — written, never read.
#  DINGER_BASE_WEIGHTS is the single live name; it's now also recorded in



# ────────────────────────────────────────────────────────────────────────────
def smash_tier(hr_score, pitcher_grade, env_boost, lineup_confirmed=True):
    """Return the smash-tier label for one hitter, or "" for none.

    THE canonical smash logic. hr_score = 0-99 composite; pitcher_grade =
    opposing pitcher grade string; env_boost = park×weather×wind multiplier;
    lineup_confirmed = the hitter is in the confirmed starting lineup
    (v45.14: restored — the override had dropped this documented gate; an
    unconfirmed hitter can't be a smash spot no matter the score).
    Rules: never smash vs an ELITE/TOUGH pitcher, AND require an EXPLOIT/EXPLOIT+
    pitcher (a MIXED/neutral pitcher does NOT qualify for any smash tier — this
    matches the user-facing legend everywhere: "HR Score ≥N + EXPLOIT/EXPLOIT+
    pitcher + env gate"). Given an EXPLOIT pitcher, tier by HR Score + a
    favorable/neutral env gate. Referenced by both the scoring override and the
    caption text so they can never drift.
    (v46.51 review-response: the prior one-line docstring said only "otherwise
    tier by HR Score + env", omitting the EXPLOIT requirement — a reviewer read
    that as a bug where MIXED pitchers were wrongly excluded. The CODE is correct
    and matches the legend; the docstring was incomplete. Fixed here.)
    """
    if not lineup_confirmed:
        return ""
    _pg = str(pitcher_grade or "").upper()
    # Hostile pitcher (ace) blocks all tiers.
    if "ELITE" in _pg or "TOUGH" in _pg:
        return ""
    _favorable_pitcher = ("EXPLOIT" in _pg)  # EXPLOIT or EXPLOIT+
    if not _favorable_pitcher:
        return ""
    try:
        _sc = float(hr_score) if hr_score is not None and not pd.isna(hr_score) else 0.0
    except (TypeError, ValueError):
        _sc = 0.0
    try:
        _env = float(env_boost) if env_boost is not None and not pd.isna(env_boost) else 0.0
    except (TypeError, ValueError):
        _env = 0.0
    _env_favorable = _env >= SMASH_ENV_FAVORABLE
    _env_neutral = _env >= SMASH_ENV_NEUTRAL
    if _sc >= SMASH_ELITE_SCORE and _env_favorable:
        return "🔥🔥🔥 ELITE SMASH"
    if _sc >= SMASH_STRONG_SCORE and _env_neutral:
        return "🔥🔥 STRONG SMASH"
    if _sc >= SMASH_BASE_SCORE and _env_neutral:
        return "🔥 SMASH"
    return ""

# ────────────────────────────────────────────────────────────────────────────
def pa_threshold_for_date(d: date) -> int:
    """PA threshold scales with how deep into the season we are.

    v43.18 (reviewer-validated): uses shared _season_phase from models.py
    so this and _season_thresholds stay in lockstep on date logic.

    v43.54 (reviewer fix #3): the previous except-fallback re-implemented
    the month→phase switch inline, which would drift from _season_phase
    if MLB ever shifts to a March opener. Now if _season_phase import
    fails, we use a single safe default ("june") and surface the failure.
    Single source of truth — no parallel logic to maintain.
    """
    try:
        from models import _season_phase
        phase = _season_phase(d)
    except Exception:
        # Defensive: if _season_phase is unavailable for any reason,
        # default to mid-season threshold (june → 120 PA). This is the
        # SAFEST default for an unknown phase. The only cost: an October
        # slate during an import-broken state gets 120 PA instead of 280.
        # Better than maintaining a drift-prone month-switch duplicate.
        phase = "june"
    # v43.64 (reviewer doc fix #6): the .get(phase, 200) default below is
    # defensive but unreachable in practice — _season_phase only ever
    # returns one of the 8 dict keys. Kept as belt-and-suspenders in case
    # _season_phase grows new phases in the future. "june fallback (120)"
    # above and "dict-default fallback (200)" here are two different
    # defenses for two different failure modes (import-broken vs. unknown
    # phase string from a future schema), not redundant safety nets.
    return {
        "early": 40, "may": 80, "june": 120,
        # v46.30: Aug/Sep lowered (200→170, 250→210). Even everyday regulars vary,
        # and post-deadline rosters churn heavily — the old floors were a touch
        # high. The peripheral-qualify path (in the pick pool) is the main fix;
        # this just relaxes the primary floor to match a real league's PA spread.
        "july": 160, "august": 170,
        "september": 210, "october": 280, "offseason": 200,
    }.get(phase, 170)

# ────────────────────────────────────────────────────────────────────────────
def hr_verdict(hr_game_pct, sample_size=None, pa_threshold=80):
    """Inline tier for HR Game% display."""
    if hr_game_pct is None or pd.isna(hr_game_pct):
        return ""
    if sample_size is not None and not pd.isna(sample_size) and sample_size < pa_threshold:
        return "⚠️ SMALL"
    if hr_game_pct >= 25:
        return "🔥 ELITE"
    if hr_game_pct >= 18:
        return "✅ STRONG"
    if hr_game_pct >= 12:
        return "📊 SOLID"
    if hr_game_pct >= 5:
        return "💤 WEAK"
    return "❌ AVOID"

# ────────────────────────────────────────────────────────────────────────────
def hr_signal_emoji(hr_game_pct, sample_size=None, pa_threshold=80,
                     same_side_platoon=False, env_mult=None):
    """Single emoji for the Signal column - hitters.

    v43.4 FIX (reviewer-validated): Signal is now DERIVED FROM GRADE so they
    can never disagree. Previously:
      - Green started at 22% but grade A started at 21% → 21.0-21.9% band was
        yellow+A (Canzone/Carpenter at 21.5% surfaced this)
      - Grade applied same-side-platoon cap but signal ignored handedness →
        Dingler 22.5% RvR was green but grade B+ (capped from A)

    Now: A+/A → 🟢, B+/B → 🟡, C+/C → 🟠, D/F → 🔴. Inherits the platoon cap
    and PA gate automatically. Colors will always match the letter.

    v45.12 (review P1 #1): also forwards env_mult, so an env-capped grade
    (env<0.85, e.g. A→B+) yields the matching capped signal — otherwise the
    signal recomputed an UNcapped grade and drifted from the displayed letter.
    """
    grade = hr_grade(hr_game_pct, sample_size=sample_size,
                     pa_threshold=pa_threshold,
                     same_side_platoon=same_side_platoon,
                     env_mult=env_mult)
    if grade in ("A+", "A"):
        return "🟢"
    if grade in ("B+", "B"):
        return "🟡"
    if grade in ("C+", "C"):
        return "🟠"
    if grade in ("D", "F"):
        return "🔴"
    return "⚪"

# ────────────────────────────────────────────────────────────────────────────
def hr_grade(hr_game_pct, sample_size=None, pa_threshold=80,
              same_side_platoon=False, env_mult=None):
    """Letter grade (A+/A/B+/B/C/D/F) for HR Game% - more intuitive than %.

    SAME-SIDE PLATOON CAP (v38g): LvL and RvR matchups are inherently tougher
    than the projected HR% suggests. Cap same-side matchups one tier down:
    A+ → A, A → B+.

    v43.21 (user-requested): ENVIRONMENT HOSTILITY TIER-CAP. The HR Game%
    DOES already include env (park/weather/wind), but the [0.65, 1.35] cap
    on ctx_mult softens extreme hostility — a hitter who'd naturally drop
    to 14% in a brutal env gets clipped at ~17%, which still grades B+.
    Adding an explicit tier-cap when env_mult is below 0.85 makes the
    grade reflect "this environment is actively working against this
    hitter" without changing the underlying probability calculation. Same
    pattern as same_side_platoon cap.

    Caps applied (only triggered when env_mult < 0.85):
      A+ → A    (clear suppression)
      A  → B+
      B+ → B
      (B and below not capped further — already moderate grades)

    NEW CALIBRATION:
      A+ : ≥25%  (rare elite, top 3-5% of plays)
      A  : 21-25% (strong, top 10%)
      B+ : 17-21% (above average, top 25%)
      B  : 13-17% (solid)
      C+ : 10-13% (modest)
      C  : 7-10%  (below average)
      D  : 4-7%   (poor)
      F  : <4%    (avoid)
    """
    if hr_game_pct is None or pd.isna(hr_game_pct):
        return "—"
    # v43.10: removed the `sample_size < pa_threshold` short-circuit that
    # used to return "—". Grade is now computed from the (shrunk) HR Game%
    # for every hitter with valid data. Sample-size warning lives in the
    # pa_confidence flag instead.
    if hr_game_pct >= 25:
        raw = "A" if same_side_platoon else "A+"
    elif hr_game_pct >= 21:
        raw = "B+" if same_side_platoon else "A"
    elif hr_game_pct >= 17:
        raw = "B+"
    elif hr_game_pct >= 13:
        raw = "B"
    elif hr_game_pct >= 10:
        raw = "C+"
    elif hr_game_pct >= 7:
        raw = "C"
    elif hr_game_pct >= 4:
        raw = "D"
    else:
        raw = "F"

    # v43.21: ENV HOSTILITY TIER-CAP — display-level adjustment, doesn't
    # change underlying hr_game_pct. The probability calculation already
    # softens via the ctx_mult floor; this caps the LETTER GRADE so a
    # hitter in a hostile env can't show as A even if their season
    # power-line keeps the % elevated.
    if env_mult is not None and not pd.isna(env_mult):
        try:
            env_f = float(env_mult)
            if env_f < 0.85:
                _CAP = {"A+": "A", "A": "B+", "B+": "B"}
                raw = _CAP.get(raw, raw)
        except (TypeError, ValueError):
            pass
    return raw

# ────────────────────────────────────────────────────────────────────────────
def pa_confidence_tier(sample_size):
    """v43.10: tiered confidence indicator for a hitter's season PA sample.

    Displayed alongside the grade so users can see at a glance how reliable
    the projection is. The grade itself is the same formula for everyone;
    this tier surfaces uncertainty without hiding the data.

    ✅ confident  : ≥150 PA — well-sampled, trust the grade as-is
    📊 normal     : 75-149 PA — reasonable, slight noise
    ⚠️ small      : 30-74 PA — caution, projection heavily weighted to league mean
    ❓ very small : <30 PA   — mostly priors, treat as speculative
    """
    if sample_size is None or pd.isna(sample_size):
        return "❓"
    try:
        pa = float(sample_size)
    except (TypeError, ValueError):
        return "❓"
    if pa >= 150:
        return "✅"
    if pa >= 75:
        return "📊"
    if pa >= 30:
        return "⚠️"
    return "❓"

# ────────────────────────────────────────────────────────────────────────────
def pitcher_signal_emoji(test_score, sample_size=None, pa_threshold=80):
    """Single emoji for the Signal column - pitchers."""
    if test_score is None or pd.isna(test_score):
        return "⚪"
    if sample_size is not None and not pd.isna(sample_size) and sample_size < pa_threshold:
        return "⚪"
    if test_score >= 65:
        return "🟢"
    if test_score >= 45:
        return "🟡"
    if test_score >= 30:
        return "🟠"
    return "🔴"

# ────────────────────────────────────────────────────────────────────────────
def pitcher_grade(test_score, hr_suppress=None, sample_size=None, pa_threshold=80,
                    era=None, hr9=None, ip=None):
    """Letter grade + label for pitchers — matches BetGravy style.

    Combines test_score (K-focused) and hr_suppress (HR-friendly avoidance)
    to produce a pitcher matchup grade from the batter's perspective. This
    grade reflects the PITCHER'S SKILL ONLY — park and weather are NOT
    factored in (use env_adj_grade for that, which adjusts for tonight's
    environment).

      EXPLOITABLE+ : test ≤ 30 OR hr_suppress ≤ 30  (target this pitcher)
      EXPLOITABLE  : test ≤ 45 OR hr_suppress ≤ 45
      MIXED        : test 45-65, hr_suppress 45-65 (neutral)
      TOUGH        : test ≥ 65 AND hr_suppress ≥ 65
      ELITE        : test ≥ 80 AND hr_suppress ≥ 75 (avoid HR plays here)

    v38 fallback (Feltner case): When Savant-derived test_score is NaN but
    we have basic MLB Stats API data (ERA + HR/9), assign a simplified grade
    from those two. Prevents pitchers with real data from showing "—" just
    because the Statcast merge failed silently.

    v38e fix (Feltner reprise): The original v38 fallback required PA ≥ 80,
    but PA comes from the same Savant fetch that failed — so PA was also
    NaN, and the fallback never fired. Now we also accept IP ≥ 10 as the
    sample threshold (matches the IP gate used elsewhere). MLB Stats API
    returns IP reliably even when Savant data is missing.
    """
    # Helper: try the ERA/HR9 fallback grade. Returns a grade string if
    # the inputs allow one, otherwise returns None.
    def _era_hr9_fallback():
        # Need a sample — either PA or IP
        has_sample = False
        if (sample_size is not None and not pd.isna(sample_size)
                and sample_size >= pa_threshold):
            has_sample = True
        elif ip is not None and not pd.isna(ip):
            try:
                if float(ip) >= 10.0:
                    has_sample = True
            except (TypeError, ValueError):
                pass
        if not has_sample:
            return None
        if era is None or pd.isna(era) or hr9 is None or pd.isna(hr9):
            return None
        try:
            era_f = float(era)
            hr9_f = float(hr9)
        except (TypeError, ValueError):
            return None
        # Simple fallback grade from ERA + HR/9:
        #   ELITE:    era < 2.75 AND hr9 < 0.80
        #   TOUGH:    era < 3.50 AND hr9 < 1.00
        #   EXPLOIT+: era >= 5.00 OR hr9 >= 1.80
        #   EXPLOIT:  era >= 4.25 OR hr9 >= 1.40
        #   MIXED:    everything else
        if era_f < 2.75 and hr9_f < 0.80:
            raw_grade = "ELITE"
        elif era_f < 3.50 and hr9_f < 1.00:
            raw_grade = "TOUGH"
        elif era_f >= 5.00 or hr9_f >= 1.80:
            raw_grade = "EXPLOIT+"
        elif era_f >= 4.25 or hr9_f >= 1.40:
            raw_grade = "EXPLOIT"
        else:
            raw_grade = "MIXED"

        # SAMPLE-SIZE SHRINKAGE (v39j)
        # ERA and HR/9 over <30 IP are too noisy to support extreme positive
        # grades. The Gage Jump case: 18 IP, ERA 2.45, HR/9 0.00 → fallback
        # says ELITE, but that's pure small-sample noise.
        #
        # v43.20 (reviewer-validated): symmetric shrinkage. Previous v39j
        # only shrunk ELITE/TOUGH on the theory that "high ERA in small
        # sample = real bad pitcher." Senga at 20 IP / 9.00 ERA shows that
        # was wrong — returning-from-injury and other context can produce
        # spuriously bad small samples too. Now both sides shrink.
        #
        #   IP < 15:  force MIXED regardless of starting grade. Below 15 IP
        #             is barely 2-3 starts — no grade is reliable.
        #   IP 15-29: down-shift one tier (ELITE→TOUGH, TOUGH→MIXED,
        #             EXPLOIT+→EXPLOIT, EXPLOIT→MIXED).
        #   IP ≥ 30:  no adjustment — large enough sample to grade.
        if ip is not None and not pd.isna(ip):
            try:
                ip_f = float(ip)
                if ip_f < 15:
                    if raw_grade in ("ELITE", "TOUGH", "EXPLOIT", "EXPLOIT+"):
                        return "MIXED"
                elif ip_f < 30:
                    if raw_grade == "ELITE":
                        return "TOUGH"
                    if raw_grade == "TOUGH":
                        return "MIXED"
                    if raw_grade == "EXPLOIT+":
                        return "EXPLOIT"
                    if raw_grade == "EXPLOIT":
                        return "MIXED"
            except (TypeError, ValueError):
                pass
        return raw_grade

    if test_score is None or pd.isna(test_score):
        # No Savant test_score → try ERA/HR9 fallback
        fb = _era_hr9_fallback()
        return fb if fb else "—"
    # NO sample (NaN/None) = insufficient. A pitcher with no PA faced shouldn't
    # get a grade. v39f fix: but if Savant returned test_score on low PA AND
    # we have ERA+HR9+IP from MLB Stats API, still grade from the fallback.
    # This catches Gage Jump (test_score from Savant but PA<80; ERA 3.75,
    # HR/9 0.00, IP 12 — fallback now grades him TOUGH instead of —).
    if sample_size is None or pd.isna(sample_size) or sample_size < pa_threshold:
        fb = _era_hr9_fallback()
        return fb if fb else "—"
    hr_s = hr_suppress if (hr_suppress is not None and not pd.isna(hr_suppress)) else test_score
    # Combined indicator - higher = harder to score against
    combined_min = min(test_score, hr_s)
    combined_max = max(test_score, hr_s)
    avg = (test_score + hr_s) / 2

    # First-pass grade from slate-relative percentile
    if avg >= 80 and combined_min >= 70:
        raw_grade = "ELITE"
    elif avg >= 65 and combined_min >= 55:
        raw_grade = "TOUGH"
    elif combined_max <= 30 or combined_min <= 25:
        raw_grade = "EXPLOIT+"
    elif combined_max <= 45 or combined_min <= 35:
        raw_grade = "EXPLOIT"
    else:
        raw_grade = "MIXED"

    # v43.20 (reviewer-validated, structural fix): the slate-relative
    # percentile thresholds above mean ~25-30% of every slate is graded
    # EXPLOIT+ by definition. On a slate of aces, the worst ace becomes
    # EXPLOIT+. An absolute-sounding grade ("target this pitcher") should
    # not be derived purely from a relative score.
    #
    # ABSOLUTE METRIC BACKSTOP: require real ERA/HR9 to support
    # EXPLOIT/EXPLOIT+ tiers. A pitcher in the slate's bottom percentile
    # who actually has a respectable ERA stays MIXED.
    #   EXPLOIT+ requires: era >= 4.50 OR hr9 >= 1.40
    #   EXPLOIT  requires: era >= 3.75 OR hr9 >= 1.15
    # If neither metric is available, the slate-relative grade stands
    # (no harm done in that edge case — likely a fresh call-up).
    if raw_grade in ("EXPLOIT", "EXPLOIT+"):
        try:
            era_f = float(era) if (era is not None and not pd.isna(era)) else None
            hr9_f = float(hr9) if (hr9 is not None and not pd.isna(hr9)) else None
        except (TypeError, ValueError):
            era_f, hr9_f = None, None

        if era_f is not None or hr9_f is not None:
            era_ok = era_f is not None and era_f >= 4.50
            hr9_ok = hr9_f is not None and hr9_f >= 1.40
            if raw_grade == "EXPLOIT+" and not (era_ok or hr9_ok):
                # Doesn't meet absolute EXPLOIT+ threshold — try EXPLOIT
                era_ok_e = era_f is not None and era_f >= 3.75
                hr9_ok_e = hr9_f is not None and hr9_f >= 1.15
                if era_ok_e or hr9_ok_e:
                    raw_grade = "EXPLOIT"
                else:
                    raw_grade = "MIXED"
            elif raw_grade == "EXPLOIT":
                era_ok_e = era_f is not None and era_f >= 3.75
                hr9_ok_e = hr9_f is not None and hr9_f >= 1.15
                if not (era_ok_e or hr9_ok_e):
                    raw_grade = "MIXED"

    # v43.20: SYMMETRIC small-sample shrinkage. Previously only ELITE/TOUGH
    # were shrunk on the assumption "high ERA in small sample is real, low
    # ERA in small sample is luck." The reviewer's Senga-at-20-IP case is
    # the counterexample: 9.00 ERA in 20 IP from a returning-from-injury
    # pitcher is exactly the noise this shrinkage was built for. Now both
    # sides shrink symmetrically.
    if ip is not None and not pd.isna(ip):
        try:
            ip_f = float(ip)
            if ip_f < 15:
                if raw_grade in ("ELITE", "TOUGH", "EXPLOIT", "EXPLOIT+"):
                    raw_grade = "MIXED"
            elif ip_f < 30:
                if raw_grade == "ELITE":
                    raw_grade = "TOUGH"
                elif raw_grade == "TOUGH":
                    raw_grade = "MIXED"
                elif raw_grade == "EXPLOIT+":
                    raw_grade = "EXPLOIT"
                elif raw_grade == "EXPLOIT":
                    raw_grade = "MIXED"
        except (TypeError, ValueError):
            pass

    return raw_grade

# ────────────────────────────────────────────────────────────────────────────
def pitcher_grade_env_adj(base_grade, env_mult):
    """Adjust the base pitcher grade for tonight's park × weather.

    The intuition: an ELITE pitcher in Coors with wind out (env_mult=1.20)
    is closer to TOUGH in HR-suppression terms tonight, and an EXPLOIT
    pitcher in Petco with cold wind in (env_mult=0.80) is closer to MIXED.

    Rules (env_mult is the game's park × weather HR multiplier):
      env >= 1.18 (very hitter-friendly):  shift one tier toward EXPLOIT
      env >= 1.10 (hitter-friendly):       shift half a tier (only soft tiers)
      env <= 0.85 (pitcher-friendly):      shift one tier toward TOUGH
      env <= 0.92 (mildly pitcher-friendly): shift half a tier (only soft tiers)
      else: no change

    Half-tier means: a borderline grade gets nudged; established tiers
    (ELITE / EXPLOIT+) hold unless the env shift is strong.
    """
    if base_grade in (None, "—"):
        return "—"
    if env_mult is None or pd.isna(env_mult):
        return base_grade

    em = float(env_mult)
    order = ["EXPLOIT+", "EXPLOIT", "MIXED", "TOUGH", "ELITE"]
    if base_grade not in order:
        return base_grade
    idx = order.index(base_grade)

    if em >= 1.18:
        new_idx = max(0, idx - 1)
    elif em >= 1.10:
        # Soft shift: only nudge MIXED→EXPLOIT and TOUGH→MIXED. Don't drag
        # ELITE down for a mild park boost.
        if base_grade in ("MIXED", "TOUGH"):
            new_idx = idx - 1
        else:
            new_idx = idx
    elif em <= 0.85:
        new_idx = min(len(order) - 1, idx + 1)
    elif em <= 0.92:
        if base_grade in ("EXPLOIT", "MIXED"):
            new_idx = idx + 1
        else:
            new_idx = idx
    else:
        new_idx = idx
    return order[new_idx]

# ────────────────────────────────────────────────────────────────────────────
def pitcher_grade_sort_key(grade):
    """Return numeric sort key for pitcher grade. Lower = more exploitable.
    Used so users can sort the grade column and get a sensible order.

    From batter perspective: EXPLOIT+ is BEST (target), ELITE is WORST (avoid).
    Sort ascending → most exploitable first (best for HR betting).
    """
    order = {
        "EXPLOIT+": 1,
        "EXPLOIT": 2,
        "MIXED": 3,
        "TOUGH": 4,
        "ELITE": 5,
        "—": 99,  # insufficient data goes last
    }
    return order.get(grade, 99)

# ────────────────────────────────────────────────────────────────────────────
# LaunchCast 2.0 auto-reweight override.
# DINGER_BASE_WEIGHTS is the shipped default. _ACTIVE_DINGER_WEIGHTS is what
# scoring ACTUALLY uses — it defaults to the shipped constant, but can be
# overridden at startup with evidence-driven auto-applied weights loaded from
# the durable gist (see auto_reweight.load_live_weights + set_active_dinger_weights).
# If anything about the override is wrong, we ALWAYS fall back to the constant,
# so scoring can never break or use garbage weights.
_ACTIVE_DINGER_WEIGHTS = dict(DINGER_BASE_WEIGHTS)


def set_active_dinger_weights(weights) -> bool:
    """Override the live dinger weights (called once at startup with gist-loaded
    auto-applied weights). Bulletproof: rejects anything that isn't a clean dict
    with the SAME keys as the shipped default and all-positive finite values —
    on any problem it leaves the safe default in place and returns False."""
    global _ACTIVE_DINGER_WEIGHTS
    try:
        if not isinstance(weights, dict):
            return False
        if set(weights.keys()) != set(DINGER_BASE_WEIGHTS.keys()):
            return False
        clean = {}
        for k, v in weights.items():
            fv = float(v)
            if not (fv > 0) or fv != fv or fv in (float("inf"), float("-inf")):
                return False
            clean[k] = fv
        _ACTIVE_DINGER_WEIGHTS = clean
        return True
    except Exception:
        return False


def active_dinger_weights() -> dict:
    """Return the weights scoring is currently using (default or auto-applied)."""
    return dict(_ACTIVE_DINGER_WEIGHTS)


def _dinger_base_percentile(df: "pd.DataFrame") -> "pd.Series":
    """Percentile-ranked raw power base (0-100), per-row NaN-renormalized."""
    present = [(c, w) for c, w in _ACTIVE_DINGER_WEIGHTS.items() if c in df.columns]
    if not present:
        return pd.Series(np.nan, index=df.index)
    num = pd.Series(0.0, index=df.index)
    den = pd.Series(0.0, index=df.index)
    for col, w in present:
        s = pd.to_numeric(df[col], errors="coerce")
        if s.notna().sum() == 0:
            continue
        pct = s.rank(pct=True) * 100.0
        mask = pct.notna()
        num = num.add((pct.fillna(0) * w) * mask.astype(float), fill_value=0)
        den = den.add(mask.astype(float) * w, fill_value=0)
    return num / den.replace(0, np.nan)

# ────────────────────────────────────────────────────────────────────────────
def compute_dinger_score(df: "pd.DataFrame", context: bool = True) -> "pd.Series":
    """Dinger Score v2: raw-power base tilted by tonight's context.

    Args:
        df: hitter frame (needs the base columns; context columns optional).
        context: if True (default), apply recency/park-weather/matchup
                 multipliers so the score moves per slate. If False, returns
                 the pure season-power percentile (used by the builder preset
                 so that view stays a clean season-power ranking).

    Returns 0-100 Series. NaN for a hitter with no base inputs.
    """
    if df is None or df.empty:
        return pd.Series(dtype=float)
    base = _dinger_base_percentile(df)
    if not context:
        _bscore = base.round(1)
        _apply_dinger_tiebreak(df, _bscore)
        return _bscore

    mult = pd.Series(1.0, index=df.index)

    # Recency: recent HR-weighted rate, percentile-centered so above-median
    # form lifts and below-median form drags. Falls back to hr_last_10.
    _rec_col = "recent_hr_weighted_rate" if "recent_hr_weighted_rate" in df.columns \
        else ("hr_last_10" if "hr_last_10" in df.columns else None)
    if _rec_col:
        r = pd.to_numeric(df[_rec_col], errors="coerce")
        if r.notna().sum() > 0:
            rp = r.rank(pct=True)  # 0-1
            # center at 0.5 → multiplier in [1-w, 1+w]
            mult = mult * (1.0 + DINGER_CONTEXT["recency"] * (rp.fillna(0.5) - 0.5) * 2)

    # Environment: env_boost is already a multiplier (~0.8-1.2). Blend a
    # dampened version so it nudges rather than dominates.
    if "env_boost" in df.columns:
        e = pd.to_numeric(df["env_boost"], errors="coerce").fillna(1.0)
        mult = mult * (1.0 + DINGER_CONTEXT["env"] * (e - 1.0) / 0.20)

    # Matchup: matchup_opp (0-100, higher = better hitter spot). Center at 50.
    if "matchup_opp" in df.columns:
        m = pd.to_numeric(df["matchup_opp"], errors="coerce")
        if m.notna().sum() > 0:
            mp = (m.fillna(50) - 50) / 50.0  # -1..+1
            mult = mult * (1.0 + DINGER_CONTEXT["matchup"] * mp)

    mult = mult.clip(0.70, 1.35)
    _score = (base * mult).clip(0, 100).round(1)
    _apply_dinger_tiebreak(df, _score)
    return _score

# ────────────────────────────────────────────────────────────────────────────
def _apply_dinger_tiebreak(df: "pd.DataFrame", score: "pd.Series") -> None:
    """v44.31: set df['dinger_score_precise'] = score + a sub-0.1 nudge from
    the highest-signal HR predictors, so tied displayed scores still rank
    meaningfully (by who's stronger in the most HR-predictive stat). The
    displayed dinger_score stays the clean rounded value; this is sort-only.
    Priority order = Section G's most reliable predictors, decaying so the
    first (pulled_brl_pct) dominates ties.

    SAFETY (v45.09 correction): this is safe NOT because the nudge is small
    enough to never flip a rounded value — the max nudge (~0.0969) CAN cross a
    round(1) boundary. It's safe because the nudge lands ONLY in the separate
    dinger_score_precise column (used for sorting); the DISPLAYED dinger_score
    is the un-nudged rounded value. Do NOT fold precise back into the display —
    the magnitude bound does not protect it, the column separation does."""
    try:
        _tb = pd.Series(0.0, index=df.index)
        for _i, _c in enumerate(["pulled_brl_pct", "barrel_pct", "avg_ev",
                                  "iso", "hard_hit"]):
            if _c in df.columns:
                _s = pd.to_numeric(df[_c], errors="coerce")
                if _s.notna().any():
                    _tb = _tb + _s.rank(pct=True).fillna(0.5) * (0.05 / (2 ** _i))
        df["dinger_score_precise"] = (score.fillna(0) + _tb).round(4)
    except Exception:
        df["dinger_score_precise"] = score

# ────────────────────────────────────────────────────────────────────────────
def tag_power_targets(df: "pd.DataFrame") -> "pd.DataFrame":
    """v44.18: mark each game's Moonshot + Laser target as gradeable columns.

    Adds two int columns to df (in place, returns df):
      is_moonshot_target — 1 for the single hitter per game most likely to hit
                           a 400+ ft HR (carry proxy: barrel/pull-air/blast/
                           pulled-brl/ISO + tonight's matchup, or real
                           avg_hr_distance when present).
      is_laser_target    — 1 for the hitter per game most likely to hit a
                           105+ mph HR (avg_ev/hard_hit + matchup).

    Computed here — UPSTREAM of snapshotting — so these picks flow into the
    daily snapshot and the learning loop can grade whether the moonshot/laser
    target actually produced the outcome. The per-game display reads these
    columns instead of recomputing. Mirrors the v44.05 blend + shrinkage.
    """
    # v46.07 (review): guard BEFORE assignment — df["..."]=0 on a None df
    # crashes with TypeError. Check first, then assign.
    if df is None or getattr(df, "empty", True) or "game" not in getattr(df, "columns", []):
        return df
    df["is_moonshot_target"] = 0
    df["is_laser_target"] = 0

    def _pick_for_game(g: "pd.DataFrame", components, min_hr=5.0):
        _g = g
        if "is_bench" in _g.columns:
            _g = _g[~_g["is_bench"].fillna(False).astype(bool)]
        if "hr_game_pct" in _g.columns:
            _g = _g[pd.to_numeric(_g["hr_game_pct"], errors="coerce").notna()]
        if _g.empty:
            return None
        # volume for shrinkage
        _vol = None
        for _vc in ("pa", "bbe", "batted_balls", "ab"):
            if _vc in _g.columns:
                s = pd.to_numeric(_g[_vc], errors="coerce")
                if s.notna().any():
                    _vol = s
                    break
        shrink = ((_vol / (_vol + 60.0)).clip(0.4, 1.0)
                  if _vol is not None else pd.Series(1.0, index=_g.index))
        present = []
        for col, w in components:
            if col in _g.columns:
                s = pd.to_numeric(_g[col], errors="coerce")
                if s.notna().any():
                    present.append((s, w))
        if not present:
            return None
        num = pd.Series(0.0, index=_g.index)
        den = pd.Series(0.0, index=_g.index)
        for s, w in present:
            pct = s.rank(pct=True) * 100.0
            pct = 50.0 + (pct - 50.0) * shrink
            mask = s.notna()
            num = num.add((pct.fillna(0) * w) * mask.astype(float), fill_value=0)
            den = den.add(mask.astype(float) * w, fill_value=0)
        score = num / den.replace(0, np.nan)
        hrp = pd.to_numeric(_g.get("hr_game_pct"), errors="coerce")
        elig = score[hrp >= min_hr].dropna() if hrp is not None else score.dropna()
        if elig.empty:
            elig = score.dropna()
        if elig.empty:
            return None
        return elig.idxmax()

    def _score_for_group(g: "pd.DataFrame", components):
        # v44.78: same composite as _pick_for_game but returns the FULL score
        # series (aligned to g's index), not just the winner — for slate-wide
        # ranking. Bench excluded (matches the per-game flag behavior).
        _g = g
        if "is_bench" in _g.columns:
            _g = _g[~_g["is_bench"].fillna(False).astype(bool)]
        if _g.empty:
            return None
        _vol = None
        for _vc in ("pa", "bbe", "batted_balls", "ab"):
            if _vc in _g.columns:
                s = pd.to_numeric(_g[_vc], errors="coerce")
                if s.notna().any():
                    _vol = s
                    break
        shrink = ((_vol / (_vol + 60.0)).clip(0.4, 1.0)
                  if _vol is not None else pd.Series(1.0, index=_g.index))
        present = []
        for col, w in components:
            if col in _g.columns:
                s = pd.to_numeric(_g[col], errors="coerce")
                if s.notna().any():
                    present.append((s, w))
        if not present:
            return None
        num = pd.Series(0.0, index=_g.index)
        den = pd.Series(0.0, index=_g.index)
        for s, w in present:
            pct = s.rank(pct=True) * 100.0
            pct = 50.0 + (pct - 50.0) * shrink
            mask = s.notna()
            num = num.add((pct.fillna(0) * w) * mask.astype(float), fill_value=0)
            den = den.add(mask.astype(float) * w, fill_value=0)
        return num / den.replace(0, np.nan)

    _has_dist = "avg_hr_distance" in df.columns and \
        pd.to_numeric(df["avg_hr_distance"], errors="coerce").notna().any()
    _laser_comp = [("avg_hr_ev", 2.0), ("avg_ev", 2.5), ("hard_hit", 1.5),
                   ("barrel_pct", 1.0),
                   ("matchup_opp", 1.0), ("pitch_hr_score", 1.0),
                   ("env_boost", 0.75), ("recent_hr_weighted_rate", 0.5)]
    # v46.12 (live-data-caught: moonshot lift 0.61x — INVERTED): the old logic
    # weighted avg_hr_distance at 2.5 (the DOMINANT term) whenever distance was
    # present, and DROPPED the frequency drivers (barrel/pull_air/iso). But
    # avg_hr_distance measures how FAR a hitter's HRs travel, NOT how OFTEN they
    # homer — so it over-picked rare-but-mighty hitters (3 HRs at 430ft ranked
    # above 30 HRs at 400ft), which don't homer on a given night. Fix: keep the
    # frequency drivers as PRIMARY and use distance as a supporting signal (0.75)
    # — a moonshot pick should be a likely-HR hitter who ALSO hits them far,
    # not a distance outlier who rarely connects.
    _moon_comp = [("barrel_pct", 1.5), ("pull_air_pct", 1.5),
                  ("pulled_brl_pct", 1.25), ("blast_pct", 1.0),
                  ("iso", 1.0), ("fb_pct", 0.5), ("avg_ev", 0.5)] + \
                 ([("avg_hr_distance", 0.75)] if _has_dist else []) + \
                 [("matchup_opp", 1.0), ("pitch_hr_score", 1.0),
                  ("env_boost", 0.75), ("recent_hr_weighted_rate", 0.5)]
    try:
        # v44.78: also compute the composite score for EVERY hitter (not just
        # the per-game winner) so we can build a slate-wide Top 10 ranking. The
        # per-game flags stay for backward compat; the score columns enable the
        # overall list (where one game could supply two top plays).
        _moon_scores = pd.Series(np.nan, index=df.index)
        _laser_scores = pd.Series(np.nan, index=df.index)
        for _gm, _grp in df.groupby("game"):
            _li = _pick_for_game(_grp, _laser_comp)
            _mi = _pick_for_game(_grp, _moon_comp)
            if _li is not None:
                df.loc[_li, "is_laser_target"] = 1
            if _mi is not None:
                df.loc[_mi, "is_moonshot_target"] = 1
            # score every hitter in the group (reuse the composite helper)
            _ms = _score_for_group(_grp, _moon_comp)
            _ls = _score_for_group(_grp, _laser_comp)
            if _ms is not None:
                _moon_scores.loc[_grp.index] = _ms
            if _ls is not None:
                _laser_scores.loc[_grp.index] = _ls
        df["moonshot_score"] = _moon_scores.round(1)
        df["laser_score"] = _laser_scores.round(1)
    except Exception:
        pass
    return df
