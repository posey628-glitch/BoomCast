# LaunchCast 2.0 — Known Issues & Fixes Log

A running record of every bug, error, and gotcha we've hit — so future code
sweeps can check against it and we never re-introduce a killed bug. Newest first.

## 🔴 DEPLOYMENT / INFRASTRUCTURE

### Ephemeral snapshot storage (gist not configured)
- **Symptom:** "Gist not configured in Streamlit Secrets" / "Snapshot storage: EPHEMERAL — wiped on every redeploy"
- **Cause:** durable storage needs `gist_token` + `gist_id` secrets; a new app doesn't have them.
- **Fix:** add both secrets in Streamlit Cloud settings. For a SECOND app (LaunchCast 2.0), use a SEPARATE gist_id — two apps writing one gist can corrupt each other.

### .gitignore excluded .github/ → workflows never committed
- **Symptom:** automation (auto-snapshot/keep-awake) doesn't run.
- **Cause:** `.gitignore` had `.github/`, so workflow files never reached the repo.
- **Fix:** remove `.github/` from .gitignore; put workflows in `.github/workflows/`.

### Streamlit Cloud forced Python 3.14 → GZipResponder crash
- **Symptom:** `GZipResponder.__init__() missing 'thread_minimum_size'`
- **Cause:** Cloud grabbed newest streamlit on Python 3.14 (incompatible).
- **Fix:** (1) pin ALL deps with `==` in requirements.txt, (2) runtime.txt = `python-3.11`, (3) ★ set Python version in Streamlit Cloud DASHBOARD (Advanced settings) — the dashboard OVERRIDES runtime.txt.

### Nested-expander crash (Streamlit 1.44)
- **Symptom:** app crashes where an expander is nested inside another expander.
- **Fix:** convert inner expander to `st.container(border=True)` + markdown label. Never nest expanders.

### Workflow hung 15 minutes then cancelled
- **Symptom:** auto-snapshot job killed at 15 min.
- **Cause:** app not responding (down/slow) → curls hang full timeout.
- **Fix:** added `timeout-minutes: 6` to the job so it fails fast; verify app is actually up.

## 🔴 DATA / SCORING BUGS (real, fixed)

### Per-player analysis starved by snapshot pruning (USER-CAUGHT)
- **Symptom:** no player ever reached 8+ games in per-player section despite weeks of running.
- **Cause:** per_player_patterns reads FULL snapshots, which the 700KB size-cap prunes to ~4 days.
- **Fix (v46.54):** bank a lean per-player outcome log under a protected `_player_outcome_log` key (survives pruning); per_player reads from that.
- **Lesson:** separate "raw snapshots (prunable)" from "learning log (permanent)" BY DESIGN.

### L/R handedness split was identical (fake split)
- **Symptom:** vs-LHP and vs-RHP data identical → not a real platoon split.
- **Fix:** `_verify_split` checks that L and R actually DIFFER (>10% of hitters) before trusting; data-layer overhaul 2026-07-31.
- **Lesson:** "both sides populated" ≠ "real split" — verify they differ.

### Env over-weighting (~40% of pick_score, predicting below random)
- **Status:** instrumented, not yet cut (needs data). `power_score_no_env` + `pick_score_no_env` shadows track whether env should be removed.
- **Watch:** favorable-env HR lift running 0.56–0.72x (below 1.0 = env favorable spots homer LESS).


### Auto-reweight read evidence fields from wrong nesting (SWEEP-CAUGHT)
- **Symptom:** auto_reweight would SILENTLY never fire — read days/reliability/corr
  at top level, but propose_dinger_weights nests them under an "evidence" sub-dict.
  Always saw days=0 → bar never met → no reweight ever, with no error.
- **Fix:** added _ev() helper that reads from the nested evidence dict (and top-level
  for delta/proposed). Verified it now fires when the bar is genuinely met.
- **Lesson:** when two functions pass dicts across a seam, verify EXACT key nesting,
  not just key names. A silent no-op is worse than a crash.

## 🟠 CODE-QUALITY BUGS (from reviewer + audits, fixed)

- **Unreachable code after return** in `_reclassify` — removed dead lines.
- **Silent props import failure** — `_PROPS_IMPORT_ERR_MSG` captured but never surfaced; now warns in Pipeline Health.
- **Dead `if False:` statcast block** — removed, BUT preserved the `_hand_statcast_status_display` write the health panel needs.
- **Indentation drift** in `_render_deep_dive_card` list (12 vs 16 spaces) — fixed.
- **CSS comment wrong** — `#F5C518` labeled "electric blue", is amber/gold.
- **pick_score weights sum 0.91 not 1.0** — HARMLESS (self-normalizes per-row); documented so it's not re-flagged.
- **smash_tier docstring drift** — code correctly requires EXPLOIT pitcher; docstring was incomplete (fixed docstring, NOT code).

## ⚠️ FALSE ALARMS (verified NOT bugs — don't "fix" these)

- BvP "dead zero-weight code" — actually a functional ±5pt tiebreaker, NOT dead.
- `_recently_moved_ids` "unused" — used ~11k lines later to flag traded players 🔄.
- DINGER weights "sum ~9.996" — actually exactly 10.000.
- merge `overwrite=False` "drops data" — every call adds NEW columns, no collisions.
- hr_rate scale mismatch (fraction vs pct) — harmless, never combined, correlation is scale-invariant.

## 🛠️ PROCESS LESSONS

- **Attachments arrive EMPTY** — paste text in message body, not as file attachments.
- **`cp *.py .` can silently overwrite** in-progress wired files — caught twice.
- **"Looks unused" ≠ "is unused"** — the load-bearing statcast write nearly got dropped.
- **Verify every review finding against running code** — 2 suggested "fixes" were regressions.
- **Container resets between turns** — re-sync files at turn start.

## 🟢 IMPROVEMENTS (not bugs — enhancements added)

### Tier-by-tier backtest + scoreboard (user idea)
- **Insight:** grading the top-10 is noisy (it reshuffles on lineup confirmation).
  Grading by TIER MEMBERSHIP (Must-Have, Nuclear, Elite Convergence, Perfect Storm)
  is stable + tells you which cohorts actually predict HRs.
- **Was already ~80% built** (researcher_framework_backtest). Added: Perfect Storm
  grading (was shown but never graded), and a unified tier_summary_table scoreboard
  ranked by lift — the new daily headline view.
- **Lesson:** measurement/display improvements are safe (no scoring change); they
  help decide what to KEEP, which is the evidence that later justifies scoring changes.
