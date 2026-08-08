"""
auto_reweight.py — LaunchCast 2.0 evidence-driven automatic reweighting.

Runs unattended: reads accumulated feature-importance history, and IF (and only
if) the evidence clears a deliberately strict bar, applies a small, capped,
logged, reversible adjustment to the live DINGER weights — persisted to the
durable gist so it survives restarts.

SAFETY PHILOSOPHY (why this is safe to run unattended):
  It is SLOW, STABLE-GATED, CAPPED, COOLDOWN-LIMITED, LOGGED, and REVERSIBLE.
  It converges toward the evidence over WEEKS. It NEVER reacts to a single
  window. Every one of these guardrails exists to protect a winning model from
  chasing noise. Loosening them defeats the purpose.

The bar (ALL must hold before any change):
  1. >= AUTO_MIN_DAYS days of evidence on the features driving the change
  2. driving features have reliability >= AUTO_MIN_RELIABILITY (stable, not lucky)
  3. at most one auto-apply per AUTO_COOLDOWN_DAYS (weekly) — no day-over-day chase
  4. QUARTER-step toward the proposal (gentler than the ½-step shown in-app)
  5. per-feature move capped at AUTO_MAX_STEP; total drift capped
  6. full audit entry written per apply; prior weights kept for rollback
"""
from __future__ import annotations
import json
from datetime import date, datetime, timezone

# ── The strict bar (tune here; stricter = safer) ─────────────────────────────
AUTO_MIN_DAYS         = 25     # a full month+ of graded slates (proposal shows at 15)
AUTO_MIN_RELIABILITY  = 1.0    # |avg_corr|/std for driving features (stable signal)
AUTO_COOLDOWN_DAYS    = 7      # at most one auto-apply per week
AUTO_STEP_FRACTION    = 0.25   # QUARTER-step toward proposal (in-app shows ½)
AUTO_MAX_STEP         = 0.30   # no single weight moves more than this per apply (absolute, on the 10.0 scale)
AUTO_MAX_TOTAL_DRIFT  = 0.60   # sum of |moves| per apply capped here

_LOG_KEY      = "_auto_reweight_log"      # protected gist key — audit trail
_WEIGHTS_KEY  = "_live_dinger_weights"    # protected gist key — current live weights + history


def _today_iso() -> str:
    return date.today().isoformat()


def _days_since(iso_str: str) -> int:
    try:
        d = date.fromisoformat(iso_str[:10])
        return (date.today() - d).days
    except Exception:
        return 9999


def load_live_weights(gist_read_all, default_weights: dict) -> dict:
    """Return the current LIVE dinger weights: the auto-applied ones from the
    gist if present, else the shipped defaults. This is what scoring should use
    so auto-applies actually take effect + survive restarts."""
    try:
        snaps = gist_read_all() or {}
        rec = snaps.get(_WEIGHTS_KEY)
        if isinstance(rec, dict) and isinstance(rec.get("weights"), dict) and rec["weights"]:
            w = {k: float(v) for k, v in rec["weights"].items()}
            # sanity: same keys as default, finite, positive-ish
            if set(w.keys()) == set(default_weights.keys()) and all(v > 0 for v in w.values()):
                return w
    except Exception:
        pass
    return dict(default_weights)


def _last_apply_date(snaps: dict) -> str | None:
    log = snaps.get(_LOG_KEY) or []
    if isinstance(log, list) and log:
        applied = [e for e in log if e.get("applied")]
        if applied:
            return applied[-1].get("date")
    return None


def maybe_auto_reweight(gist_read_all, gist_write_all, importance_df,
                        current_live_weights: dict, default_weights: dict,
                        propose_fn) -> dict:
    """The main entry point — call once per grading run. Evaluates the strict
    bar and, if cleared, applies a capped quarter-step and persists it.

    Returns a small status dict describing what happened (for display/logging).
    NEVER raises — reweighting must never break the pipeline.
    """
    status = {"checked": True, "applied": False, "reason": "", "changes": {}}
    try:
        snaps = gist_read_all() or {}

        # GUARD 3: cooldown — at most one apply per AUTO_COOLDOWN_DAYS
        last = _last_apply_date(snaps)
        if last is not None and _days_since(last) < AUTO_COOLDOWN_DAYS:
            status["reason"] = f"cooldown: {_days_since(last)}d since last apply (< {AUTO_COOLDOWN_DAYS})"
            return status

        # Get the proposal from the existing (already-guardrailed) function
        proposal = propose_fn(importance_df, dict(current_live_weights))
        if not proposal or not proposal.get("reliable"):
            status["reason"] = "proposal not reliable yet (needs more evidence days)"
            return status

        feats = proposal.get("features", {})
        # GUARD 1 + 2: every DRIVING feature (nonzero delta) must clear days + reliability
        drivers = {f: d for f, d in feats.items() if abs(d.get("delta", 0.0)) > 1e-6}
        if not drivers:
            status["reason"] = "no meaningful deltas proposed"
            return status
        for f, d in drivers.items():
            if int(d.get("days", 0)) < AUTO_MIN_DAYS:
                status["reason"] = f"{f}: only {d.get('days',0)}d evidence (< {AUTO_MIN_DAYS})"
                return status
            if float(d.get("reliability", 0.0)) < AUTO_MIN_RELIABILITY:
                status["reason"] = f"{f}: reliability {d.get('reliability',0):.2f} < {AUTO_MIN_RELIABILITY}"
                return status

        # Compute a QUARTER-step (GUARD 4) with per-feature + total caps (GUARD 5)
        new_w = dict(current_live_weights)
        moves = {}
        for f, d in drivers.items():
            cur = float(current_live_weights.get(f, 0.0))
            proposed = float(d.get("proposed", cur))
            full_step = proposed - cur
            step = full_step * AUTO_STEP_FRACTION
            # cap per-feature move
            step = max(-AUTO_MAX_STEP, min(AUTO_MAX_STEP, step))
            if abs(step) > 1e-6:
                moves[f] = step
        if not moves:
            status["reason"] = "all steps rounded to ~0 (nothing to do)"
            return status
        # cap total drift
        total = sum(abs(s) for s in moves.values())
        if total > AUTO_MAX_TOTAL_DRIFT:
            scale = AUTO_MAX_TOTAL_DRIFT / total
            moves = {f: s * scale for f, s in moves.items()}

        for f, s in moves.items():
            new_w[f] = round(current_live_weights[f] + s, 4)

        # Re-normalize to the same total (keeps scale stable, like the proposal does)
        tgt = sum(default_weights.values())
        cur_total = sum(new_w.values()) or 1.0
        new_w = {f: round(v * tgt / cur_total, 4) for f, v in new_w.items()}

        # GUARD 6: persist + audit trail + keep prior for rollback
        entry = {
            "date": _today_iso(),
            "ts": datetime.now(timezone.utc).isoformat(),
            "applied": True,
            "prior_weights": dict(current_live_weights),
            "new_weights": dict(new_w),
            "moves": {f: round(s, 4) for f, s in moves.items()},
            "evidence": {f: {"days": drivers[f].get("days"),
                             "reliability": round(float(drivers[f].get("reliability", 0)), 3),
                             "corr": round(float(drivers[f].get("corr", 0)), 4)}
                         for f in moves},
            "bar": {"min_days": AUTO_MIN_DAYS, "min_reliab": AUTO_MIN_RELIABILITY,
                    "step_frac": AUTO_STEP_FRACTION, "cooldown_days": AUTO_COOLDOWN_DAYS},
        }
        log = snaps.get(_LOG_KEY) or []
        if not isinstance(log, list):
            log = []
        log.append(entry)
        log = log[-100:]  # cap audit log
        snaps[_LOG_KEY] = log
        snaps[_WEIGHTS_KEY] = {"weights": dict(new_w), "updated": _today_iso(),
                               "generation": f"auto-{_today_iso()}"}
        gist_write_all(snaps)

        status["applied"] = True
        status["reason"] = f"applied quarter-step on {len(moves)} feature(s)"
        status["changes"] = {f: round(s, 4) for f, s in moves.items()}
        return status
    except Exception as e:
        status["reason"] = f"error (non-fatal, skipped): {type(e).__name__}"
        return status


def rollback_last(gist_read_all, gist_write_all) -> dict:
    """Undo the most recent auto-apply, restoring the prior weights. Manual
    safety valve — call if an auto-apply ever looks wrong."""
    try:
        snaps = gist_read_all() or {}
        log = snaps.get(_LOG_KEY) or []
        applied = [e for e in log if e.get("applied")]
        if not applied:
            return {"rolled_back": False, "reason": "no auto-apply to roll back"}
        last = applied[-1]
        snaps[_WEIGHTS_KEY] = {"weights": dict(last["prior_weights"]),
                               "updated": _today_iso(),
                               "generation": f"rollback-{_today_iso()}"}
        log.append({"date": _today_iso(), "ts": datetime.now(timezone.utc).isoformat(),
                    "applied": False, "rollback_of": last.get("date"),
                    "restored_weights": dict(last["prior_weights"])})
        snaps[_LOG_KEY] = log[-100:]
        gist_write_all(snaps)
        return {"rolled_back": True, "restored_to": last.get("date")}
    except Exception as e:
        return {"rolled_back": False, "reason": f"error: {type(e).__name__}"}
