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
        ("Aaron Judge", "NYY", "BOS", "R", "L", "C. Criswill"),
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
        ("Jazz Chisholm Jr.", "NYY", "BOS", "L", "R", "C. Criswill"),
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
    try:
        from models import enrich_slate
        out = enrich_slate(out)
    except Exception as exc:
        st.sidebar.caption(f"ℹ️ enrich_slate unavailable: {type(exc).__name__}")
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
    except Exception as exc:
        st.sidebar.caption(f"ℹ️ props unavailable: {type(exc).__name__}")
    try:
        from sleepers import find_sleepers
        out = find_sleepers(out)
    except Exception as exc:
        st.sidebar.caption(f"ℹ️ sleepers unavailable: {type(exc).__name__}")
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
    raw["game"] = raw["game"].fillna("").mask(
        raw["game"].fillna("").eq(""),
        raw["team"].astype(str) + " @ " + raw["opponent"].astype(str)
    )
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


def _safe_val(player, col, default=np.nan, fmt_str="{:.1f}", na_str="—"):
    val = player.get(col, default)
    if pd.isna(val):
        return na_str
    return fmt_str.format(val)


inject_style()

# ── Session state: always start with demo so the app renders instantly ──
if "slate" not in st.session_state:
    st.session_state.slate = demo_slate()
    st.session_state.source_label = "Demo slate · replace with your CSV"
    st.session_state.live_key = None

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

# ── Data loading (lazy / button-driven) ──
if source_mode == "CSV upload" and upload is not None:
    raw_df, err = normalize_upload(upload)
    if err:
        st.error(f"CSV Error: {err}")
    else:
        st.session_state.slate = raw_df
        st.session_state.source_label = f"Uploaded CSV ({len(raw_df)} rows)"
        st.session_state.live_key = None

elif source_mode == "Live MLB":
    try:
        from data_fetcher import build_live_slate
        key = slate_day.isoformat()
        if st.session_state.live_key != key:
            with st.spinner("Fetching live MLB data..."):
                live_df, msg = build_live_slate(key)
                if not live_df.empty:
                    st.session_state.slate = live_df
                    st.session_state.source_label = msg
                    st.session_state.live_key = key
                else:
                    st.warning(msg)
    except Exception as e:
        st.error(f"Live data fetch failed: {type(e).__name__} - {e}")

elif source_mode == "Demo slate":
    if st.session_state.source_label != "Demo slate":
        st.session_state.slate = demo_slate()
        st.session_state.source_label = "Demo slate"
        st.session_state.live_key = None

if st.sidebar.button("Reset to Demo Slate"):
    st.session_state.slate = demo_slate()
    st.session_state.source_label = "Demo slate"
    st.session_state.live_key = None

# ── Score and Display ──
weights = presets[model]
scored = score_slate(st.session_state.slate, weights)

st.markdown(f"""
<div class="hero">
    <p class="eyebrow">{st.session_state.source_label}</p>
    <h1>⚾ LaunchCast</h1>
    <p>Scanning tonight’s power spots with a <strong>{model}</strong> profile.</p>
</div>
""", unsafe_allow_html=True)

if scored.empty:
    st.warning("No players available to score. Please upload a valid CSV or wait for Live MLB lineups.")
else:
    c1, c2, c3 = st.columns(3)
    c1.metric("Players Scanned", len(scored))
    c2.metric("Avg HR Score", f"{scored['hr_score'].mean():.1f}")
    smash_spots = scored['smash_spot'].astype(str).str.strip().ne("").sum()
    c3.metric("Top Smash Spots", smash_spots)

    st.subheader("Slate Rankings")
    
    display_cols = [
        "player_name", "team", "opponent", "opp_pitcher", "hr_score", 
        "grade", "hr_game_pct", "signal", "smash_spot", "data_coverage"
    ]
    display_cols = [c for c in display_cols if c in scored.columns]

    st.dataframe(
        scored[display_cols],
        column_config={
            "player_name": "Player",
            "team": "Team",
            "opponent": "Opp",
            "opp_pitcher": "Pitcher",
            "hr_score": "HR Score",
            "grade": "Grade",
            "hr_game_pct": "HR Prob %",
            "signal": "Signal",
            "smash_spot": "Smash Spot",
            "data_coverage": "Coverage %"
        },
        hide_index=True,
        use_container_width=True
    )

tab1, tab2 = st.tabs(["Import Guide", "About"])
with tab1:
    st.markdown("""
    ### CSV Import Guide
    To analyze your own projections, upload a CSV with the following columns:
    - **Required:** `player_name`, `team`
    - **Optional (improves scoring):** `opponent`, `bats`, `pitcher_hand`, `opp_pitcher`, `barrel_pct`, `hard_hit`, `iso`, `avg_ev`, `fb_pct`, `pitcher_hr9`, `env_boost`, `recent_hr`
    """)
with tab2:
    st.markdown("LaunchCast is an independent Streamlit rebuild of a power-hitting dashboard. Scores are relative to the loaded slate and do not constitute betting advice.")
