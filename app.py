"""LaunchCast — a lightweight MLB home-run slate dashboard.

Run with: streamlit run app.py
Upload a CSV to replace the built-in demo slate. Required: player_name, team.
All other columns are optional and are documented in the Import tab.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import streamlit as st


st.set_page_config(page_title="LaunchCast", page_icon="⚾", layout="wide")

PALETTE = {
    "ink": "#0b1220", "muted": "#64748b", "line": "#e2e8f0",
    "blue": "#2563eb", "cyan": "#06b6d4", "gold": "#f59e0b",
}


@st.cache_data(show_spinner=False)
def demo_slate() -> pd.DataFrame:
    """A useful slate on first launch; it also makes the UI easy to evaluate."""
    rng = np.random.default_rng(42)
    players = [
        ("Aaron Judge", "NYY", "BOS", "R", "L", "C. Criswell"),
        ("Shohei Ohtani", "LAD", "SF", "L", "R", "L. Webb"),
        ("Juan Soto", "NYM", "PHI", "L", "R", "A. Nola"),
        ("Yordan Alvarez", "HOU", "TEX", "L", "R", "N. Eovaldi"),
        ("Gunnar Henderson", "BAL", "TOR", "L", "R", "K. Gausman"),
        ("Kyle Schwarber", "PHI", "NYM", "L", "R", "D. Peterson"),
        ("Vladimir Guerrero Jr.", "TOR", "BAL", "R", "L", "C. Burnes"),
        ("Ronald Acuña Jr.", "ATL", "MIA", "R", "L", "R. Weathers"),
        ("Elly De La Cruz", "CIN", "CHC", "S", "R", "J. Steele"),
        ("Corey Seager", "TEX", "HOU", "L", "R", "F. Valdez"),
        ("Julio Rodríguez", "SEA", "OAK", "R", "L", "J. Sears"),
        ("Rafael Devers", "BOS", "NYY", "L", "R", "C. Rodón"),
        ("Manny Machado", "SD", "ARI", "R", "L", "E. Rodríguez"),
        ("Corbin Carroll", "ARI", "SD", "L", "R", "D. Cease"),
        ("Byron Buxton", "MIN", "CLE", "R", "L", "L. Allen"),
        ("Jazz Chisholm Jr.", "NYY", "BOS", "L", "R", "C. Criswell"),
    ]
    frame = pd.DataFrame(players, columns=["player_name", "team", "opponent", "bats", "pitcher_hand", "opp_pitcher"])
    frame["game"] = frame["team"] + " @ " + frame["opponent"]
    frame["lineup_pos"] = rng.integers(1, 7, len(frame))
    frame["barrel_pct"] = np.round(rng.uniform(7, 20, len(frame)), 1)
    frame["hard_hit"] = np.round(rng.uniform(38, 58, len(frame)), 1)
    frame["iso"] = np.round(rng.uniform(.145, .380, len(frame)), 3)
    frame["avg_ev"] = np.round(rng.uniform(87, 94, len(frame)), 1)
    frame["fb_pct"] = np.round(rng.uniform(29, 51, len(frame)), 1)
    frame["pitcher_hr9"] = np.round(rng.uniform(.7, 2.1, len(frame)), 2)
    frame["env_boost"] = np.round(rng.uniform(.86, 1.18, len(frame)), 2)
    frame["recent_hr"] = rng.integers(0, 5, len(frame))
    frame["start_time"] = [f"{6 + (i % 5)}:{'10' if i % 2 else '40'} PM ET" for i in range(len(frame))]
    return frame


def num(frame: pd.DataFrame, column: str, default: float = np.nan) -> pd.Series:
    if column not in frame:
        return pd.Series(default, index=frame.index, dtype="float64")
    return pd.to_numeric(frame[column], errors="coerce")


def percentile(series: pd.Series, higher_is_better: bool = True) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce")
    score = values.rank(pct=True, na_option="keep") * 100
    return score if higher_is_better else 100 - score


def score_slate(frame: pd.DataFrame, weights: dict[str, float]) -> pd.DataFrame:
    """Score by available signals; absent columns do not silently count as zero."""
    out = frame.copy()
    # Secondary scores are explanatory lenses. The user-selected weights below
    # remain the source of truth for the board's rank order.
    try:
        from models import enrich_slate
        out = enrich_slate(out)
    except Exception:
        pass
    signals = {
        "barrel_pct": percentile(num(out, "barrel_pct")),
        "hard_hit": percentile(num(out, "hard_hit")),
        "iso": percentile(num(out, "iso")),
        "avg_ev": percentile(num(out, "avg_ev")),
        "fb_pct": percentile(num(out, "fb_pct")),
        "pitcher_hr9": percentile(num(out, "pitcher_hr9")),
        "env_boost": percentile(num(out, "env_boost")),
        "recent_hr": percentile(num(out, "recent_hr")),
    }
    weighted, total = pd.Series(0.0, index=out.index), pd.Series(0.0, index=out.index)
    for key, weight in weights.items():
        if not weight or key not in signals:
            continue
        valid = signals[key].notna()
        weighted += signals[key].fillna(0) * weight
        total += valid.astype(float) * weight
    out["hr_score"] = (weighted / total.replace(0, np.nan)).round(1)
    out["data_coverage"] = (total / sum(weights.values()) * 100).fillna(0).round().astype(int)
    env = num(out, "env_boost", 1.0)
    out["hr_game_pct"] = (7 + out["hr_score"].fillna(0) * .17 + (env - 1) * 20).clip(4, 29).round(1)
    try:
        from props import add_hr_probabilities
        out = add_hr_probabilities(out)
        out["hr_game_pct"] = out["model_hr_game_pct"].fillna(out["hr_game_pct"]).round(1)
    except Exception:
        pass
    try:
        from sleepers import find_sleepers
        out = find_sleepers(out)
    except Exception:
        pass
    out["grade"] = pd.cut(out["hr_score"], [-1, 25, 40, 55, 70, 84, 101], labels=["F", "C", "B", "B+", "A", "A+"]).astype("string").fillna("—")
    out["signal"] = pd.cut(out["hr_score"], [-1, 40, 60, 75, 101], labels=["🔴", "🟠", "🟡", "🟢"]).astype("string").fillna("⚪")
    out["smash_spot"] = np.select(
        [(out.hr_score >= 85) & (env >= 1.0), (out.hr_score >= 72) & (env >= .94), out.hr_score >= 63],
        ["🔥🔥🔥 ELITE", "🔥🔥 STRONG", "🔥 SMASH"], default=""
    )
    return out.sort_values(["hr_score", "hr_game_pct"], ascending=False, na_position="last").reset_index(drop=True)


def normalize_upload(upload) -> tuple[pd.DataFrame | None, str | None]:
    try:
        raw = pd.read_csv(upload)
    except Exception as exc:
        return None, f"Could not read that CSV: {exc}"
    from schema import assert_schema, canonicalize
    raw = canonicalize(raw)
    missing = assert_schema(raw)
    if missing:
        return None, "; ".join(missing)
    for column, default in {"opponent": "—", "bats": "—", "pitcher_hand": "—", "opp_pitcher": "—", "game": ""}.items():
        if column not in raw:
            raw[column] = default
    if raw.empty:
        return None, "CSV has headers but no hitter rows."
    raw["game"] = raw["game"].fillna("").mask(raw["game"].fillna("").eq(""), raw["team"].astype(str) + " @ " + raw["opponent"].astype(str))
    return raw, None


def inject_style() -> None:
    st.markdown("""<style>
    .block-container {max-width: 1450px; padding-top: 2.3rem; padding-bottom: 3rem;}
    [data-testid='stMetric'] {background:#fff; border:1px solid #e2e8f0; border-radius:14px; padding:13px 16px;}
    .hero {padding:22px 26px; border-radius:18px; color:#fff; background:linear-gradient(115deg,#0f172a,#1d4ed8 65%,#06b6d4); margin-bottom:1.3rem}
    .hero h1 {font-size:2.15rem; margin:0 0 5px 0}.hero p{margin:0;color:#dbeafe}
    .eyebrow {letter-spacing:.12em;text-transform:uppercase;font-size:.7rem;font-weight:700;color:#60a5fa}
    div[data-testid='stDataFrame'] {border:1px solid #e2e8f0;border-radius:12px;overflow:hidden}
    </style>""", unsafe_allow_html=True)


inject_style()
with st.sidebar:
    st.title("⚾ LaunchCast")
    st.caption("A clearer way to scan tonight’s power spots.")
    slate_day = st.date_input("Slate date", value=date.today())
    source_mode = st.radio("Data source", ["Demo slate", "Live MLB", "CSV upload"], horizontal=True)
    upload = st.file_uploader("Import slate CSV", type="csv", help="Use your own projections or Statcast exports.")
    st.divider()
    st.subheader("Model emphasis")
    model = st.select_slider("Profile", options=["Balanced", "Power", "Matchup", "Recent form"], value="Balanced")
    st.caption("Scores are relative to the loaded slate—not betting advice.")

presets = {
    "Balanced": {"barrel_pct": 1.5, "hard_hit": 1, "iso": 1.4, "avg_ev": 1, "fb_pct": .7, "pitcher_hr9": 1.2, "env_boost": .8, "recent_hr": .7},
    "Power": {"barrel_pct": 2, "hard_hit": 1.5, "iso": 1.8, "avg_ev": 1.4, "fb_pct": 1.1, "pitcher_hr9": .5, "env_boost": .4, "recent_hr": .3},
    "Matchup": {"barrel_pct": .8, "hard_hit": .6, "iso": .8, "avg_ev": .5, "fb_pct": .5, "pitcher_hr9": 2, "env_boost": 1.5, "recent_hr": .3},
    "Recent form": {"barrel_pct": 1, "hard_hit": .8, "iso": 1, "avg_ev": .7, "fb_pct": .5, "pitcher_hr9": .8, "env_boost": .6, "recent_hr": 2},
}
if source_mode == "CSV upload":
    if upload is None:
        slate, source_label = demo_slate(), "Demo slate · upload a CSV to replace it"
        st.sidebar.info("Choose a CSV above to load your slate.")
    else:
        slate, error = normalize_upload(upload)
        if error:
            st.sidebar.error(error)
            slate = demo_slate()
            source_label = "Demo slate (upload could not be used)"
        else:
            source_label = f"Imported slate · {len(slate)} hitters"
elif source_mode == "Live MLB":
    try:
        from data_fetcher import build_live_slate
        with st.spinner("Loading MLB schedule, lineups, and season Statcast data…"):
            slate, live_status = build_live_slate(slate_day.isoformat())
        if slate.empty:
            st.sidebar.warning(live_status)
            slate, source_label = demo_slate(), "Demo slate (no live player rows available)"
        else:
            source_label = live_status
    except Exception as exc:
        st.sidebar.warning(f"Live data unavailable ({type(exc).__name__}). Showing demo slate.")
        slate, source_label = demo_slate(), "Demo slate (live source unavailable)"
elif upload:
    slate, error = normalize_upload(upload)
    if error:
        st.sidebar.error(error)
        slate = demo_slate()
        source_label = "Demo slate (upload could not be used)"
    else:
        source_label = f"Imported slate · {len(slate)} hitters"
else:
    slate, source_label = demo_slate(), "Demo slate · replace with your CSV"

scored = score_slate(slate, presets[model])
st.markdown(f"<div class='hero'><div class='eyebrow'>{slate_day:%A, %B %-d} · {source_label}</div><h1>Find the cleanest power spots.</h1><p>Transparent, slate-relative rankings built from the signals you choose.</p></div>", unsafe_allow_html=True)

top = scored.iloc[0] if not scored.empty else None
metrics = st.columns(4)
metrics[0].metric("Hitters analyzed", len(scored))
metrics[1].metric("Elite smash spots", int((scored.smash_spot == "🔥🔥🔥 ELITE").sum()))
metrics[2].metric("Best environment", f"{num(scored, 'env_boost', 1).max():.2f}×")
metrics[3].metric("Top HR game chance", f"{top.hr_game_pct:.1f}%" if top is not None else "—", top.player_name if top is not None else None)

tab_overview, tab_player, tab_games, tab_sleepers, tab_learning, tab_model, tab_import = st.tabs(["Slate board", "Player lab", "Game center", "Sleeper radar", "Learning", "Custom model", "Import guide"])

with tab_overview:
    st.subheader("Slate board")
    left, right = st.columns([3, 1])
    with left:
        search = st.text_input("Filter players or teams", placeholder="e.g. Judge or NYY", label_visibility="collapsed")
    with right:
        starters_only = st.checkbox("Hide thin-data rows", value=True)
    display = scored.copy()
    if search:
        mask = display[["player_name", "team", "opponent", "opp_pitcher"]].astype(str).apply(lambda c: c.str.contains(search, case=False, na=False)).any(axis=1)
        display = display[mask]
    if starters_only:
        display = display[display.data_coverage >= 50]
    show = [c for c in ["signal", "player_name", "team", "game", "opp_pitcher", "lineup_pos", "hr_score", "hr_game_pct", "smash_spot", "power_score", "lift_score", "matchup_score", "barrel_pct", "iso", "pitcher_hr9", "env_boost", "grade", "data_coverage"] if c in display]
    labels = {"signal": "Signal", "player_name": "Hitter", "opp_pitcher": "vs Pitcher", "hr_score": "HR Score", "hr_game_pct": "HR Game%", "power_score": "Power", "lift_score": "Lift", "matchup_score": "Matchup", "pitcher_hr9": "Pitcher HR/9", "env_boost": "Env", "data_coverage": "Data %"}
    st.dataframe(display[show].rename(columns=labels), hide_index=True, use_container_width=True, height=500,
        column_config={"HR Score": st.column_config.NumberColumn(format="%.1f"), "HR Game%": st.column_config.NumberColumn(format="%.1f%%"), "Env": st.column_config.NumberColumn(format="%.2fx")})
    st.caption("🔥 tiers are visual shortlists, not probability guarantees. A score only uses fields present in your import.")

with tab_player:
    st.subheader("Player lab")
    chosen_name = st.selectbox("Choose a hitter", scored.player_name.tolist())
    player = scored.loc[scored.player_name.eq(chosen_name)].iloc[0]
    a, b, c, d = st.columns(4)
    a.metric("HR Score", f"{player.hr_score:.1f}", player.grade)
    b.metric("HR Game%", f"{player.hr_game_pct:.1f}%")
    c.metric("Environment", f"{num(pd.DataFrame([player]), 'env_boost', 1).iloc[0]:.2f}×")
    d.metric("Data coverage", f"{player.data_coverage}%")
    st.markdown(f"**{player.player_name}** bats **{player.bats}** against **{player.opp_pitcher}** ({player.pitcher_hand}HP) in **{player.game}**. {player.smash_spot}")
    ingredients = pd.DataFrame({"Signal": ["Power score", "Lift score", "Matchup score", "Discipline score", "Barrel rate", "Hard-hit rate", "ISO", "Average exit velocity", "Fly-ball rate", "Pitcher HR/9", "Environment", "Recent HR"], "Value": [f"{num(pd.DataFrame([player]), 'power_score').iloc[0]:.1f}", f"{num(pd.DataFrame([player]), 'lift_score').iloc[0]:.1f}", f"{num(pd.DataFrame([player]), 'matchup_score').iloc[0]:.1f}", f"{num(pd.DataFrame([player]), 'discipline_score').iloc[0]:.1f}", f"{num(pd.DataFrame([player]), 'barrel_pct').iloc[0]:.1f}%", f"{num(pd.DataFrame([player]), 'hard_hit').iloc[0]:.1f}%", f"{num(pd.DataFrame([player]), 'iso').iloc[0]:.3f}", f"{num(pd.DataFrame([player]), 'avg_ev').iloc[0]:.1f} mph", f"{num(pd.DataFrame([player]), 'fb_pct').iloc[0]:.1f}%", f"{num(pd.DataFrame([player]), 'pitcher_hr9').iloc[0]:.2f}", f"{num(pd.DataFrame([player]), 'env_boost', 1).iloc[0]:.2f}×", str(int(num(pd.DataFrame([player]), 'recent_hr', 0).iloc[0]))]})
    st.dataframe(ingredients, hide_index=True, use_container_width=True)

with tab_games:
    st.subheader("Game center")
    games = scored.groupby("game", dropna=False).agg(Hitters=("player_name", "count"), Avg_score=("hr_score", "mean"), Best_score=("hr_score", "max"), Best_environment=("env_boost", "max")).sort_values("Best_score", ascending=False).reset_index()
    st.dataframe(games, hide_index=True, use_container_width=True, column_config={"Avg_score": st.column_config.NumberColumn("Avg score", format="%.1f"), "Best_score": st.column_config.NumberColumn("Best score", format="%.1f"), "Best_environment": st.column_config.NumberColumn("Best env", format="%.2fx")})
    game = st.selectbox("Inspect game", games.game.tolist())
    st.dataframe(scored.loc[scored.game.eq(game), [c for c in ["player_name", "team", "bats", "opp_pitcher", "hr_score", "hr_game_pct", "smash_spot"] if c in scored]], hide_index=True, use_container_width=True)
    if st.checkbox("Load available market totals", help="Uses ESPN's public scoreboard endpoint; odds may be unavailable or delayed."):
        try:
            from game_context import get_vegas_totals
            totals = get_vegas_totals(slate_day.isoformat())
            if totals.empty or totals["total"].notna().sum() == 0:
                st.info("No current market totals were available for this slate.")
            else:
                st.dataframe(totals, hide_index=True, use_container_width=True,
                    column_config={"total": st.column_config.NumberColumn("Game total", format="%.1f"), "away_implied": st.column_config.NumberColumn("Away implied", format="%.2f"), "home_implied": st.column_config.NumberColumn("Home implied", format="%.2f")})
        except Exception as exc:
            st.info(f"Market context is unavailable right now ({type(exc).__name__}).")

with tab_sleepers:
    st.subheader("Sleeper radar")
    st.caption("Sleeper score compares today's model strength to the player's season home-run total. It is a discovery aid, not an outcome prediction.")
    sleeper_cols = [c for c in ["player_name", "team", "game", "hr_score", "hr_game_pct", "home_run", "sleeper_score", "env_boost", "weather_note"] if c in scored]
    sleeper_series = scored.get("sleeper_score", pd.Series(index=scored.index, dtype=float))
    radar = scored.loc[sleeper_series.notna(), sleeper_cols].sort_values("sleeper_score", ascending=False)
    if radar.empty:
        st.info("Sleeper identification needs season PA and home-run totals. Live data will populate it when available.")
    else:
        st.dataframe(radar, hide_index=True, use_container_width=True)

with tab_learning:
    st.subheader("Local learning loop")
    st.caption("Save the current projection board, then later upload a small outcomes CSV (`player_id` or `player_name`, plus `hr`). Nothing is sent to a third-party storage service.")
    try:
        from backtest import grade_snapshot, list_snapshots, save_snapshot
        from pattern_analysis import calibration_summary, feature_correlation
        snapshots = list_snapshots()
        if st.button("Save current slate snapshot"):
            save_snapshot(slate_day.isoformat(), scored)
            st.success("Snapshot saved locally.")
            snapshots = list_snapshots()
        st.metric("Saved snapshots", len(snapshots))
        if snapshots:
            labels = [f"{item['slate_date']} · {item['created_at'][:16].replace('T', ' ')}" for item in snapshots]
            snapshot_index = st.selectbox("Snapshot to grade", range(len(snapshots)), format_func=lambda index: labels[index])
            outcome_file = st.file_uploader("Outcomes CSV", type="csv", key="outcomes_csv")
            if outcome_file:
                try:
                    graded = grade_snapshot(snapshot_index, pd.read_csv(outcome_file))
                    summary = calibration_summary(graded)
                    if not summary:
                        st.warning("No projection rows matched that outcomes file.")
                    else:
                        a, b, c = st.columns(3)
                        a.metric("Matched hitters", summary["n"])
                        b.metric("Actual HR rate", f"{summary['actual_hr_rate']}%")
                        c.metric("Brier score", summary["brier_score"])
                        st.dataframe(feature_correlation(graded), hide_index=True, use_container_width=True)
                except Exception as exc:
                    st.warning(f"Could not grade this file: {exc}")
        else:
            st.info("No snapshots saved yet.")
    except Exception as exc:
        st.warning(f"Learning storage is unavailable: {type(exc).__name__}")

with tab_model:
    st.subheader("Build a transparent score")
    st.caption("Adjusting a weight immediately re-ranks this slate. Missing values are excluded from that hitter’s denominator, so sparse rows are not falsely penalized.")
    custom = {}
    columns = st.columns(4)
    friendly = {"barrel_pct": "Barrel rate", "hard_hit": "Hard-hit", "iso": "ISO", "avg_ev": "Exit velocity", "fb_pct": "Fly-ball", "pitcher_hr9": "Pitcher HR/9", "env_boost": "Environment", "recent_hr": "Recent HR"}
    for i, (key, label) in enumerate(friendly.items()):
        with columns[i % 4]:
            custom[key] = st.slider(label, 0.0, 3.0, float(presets[model][key]), .1, key=f"weight_{key}")
    custom_scored = score_slate(slate, custom)
    st.dataframe(custom_scored[[c for c in ["player_name", "team", "hr_score", "hr_game_pct", "data_coverage", "smash_spot"] if c in custom_scored]].head(20), hide_index=True, use_container_width=True)

with tab_import:
    st.subheader("Bring your own slate")
    st.write("Upload a CSV in the sidebar. Only `player_name` and `team` are required; the app degrades gracefully when optional metrics are absent.")
    guide = pd.DataFrame([
        ("player_name, team", "Required", "Identity fields"),
        ("opponent, opp_pitcher, bats, pitcher_hand, game", "Optional", "Matchup context"),
        ("barrel_pct, hard_hit, iso, avg_ev, fb_pct", "Optional", "Hitter power inputs"),
        ("pitcher_hr9, env_boost, recent_hr, lineup_pos", "Optional", "Opponent / game inputs"),
    ], columns=["Columns", "Status", "Purpose"])
    st.dataframe(guide, hide_index=True, use_container_width=True)
    st.download_button("Download CSV template", data="player_name,team,opponent,opp_pitcher,bats,pitcher_hand,barrel_pct,hard_hit,iso,avg_ev,fb_pct,pitcher_hr9,env_boost,recent_hr,lineup_pos\nExample Player,AAA,BBB,Example Pitcher,R,L,12.5,48.2,0.255,91.3,38.0,1.45,1.06,2,3\n", file_name="launchcast_slate_template.csv", mime="text/csv")

st.divider()
st.caption("LaunchCast · Built for transparent slate comparison. Verify lineups, weather, and market information independently.")
