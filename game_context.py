"""Optional game-level context from ESPN's public scoreboard endpoint."""
from __future__ import annotations

import pandas as pd
import requests
import streamlit as st


@st.cache_data(ttl=600, show_spinner=False)
def get_vegas_totals(game_date: str) -> pd.DataFrame:
    """Current listed total and team implied runs, if ESPN exposes an odds feed."""
    payload = requests.get("https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/scoreboard", params={"dates": game_date.replace("-", "")}, timeout=15).json()
    rows = []
    for event in payload.get("events", []):
        competition = event.get("competitions", [{}])[0]
        teams = competition.get("competitors", [])
        home = next((team for team in teams if team.get("homeAway") == "home"), {})
        away = next((team for team in teams if team.get("homeAway") == "away"), {})
        odds = (competition.get("odds") or [{}])[0]
        total, spread = odds.get("overUnder"), odds.get("spread")
        if total is not None:
            total, spread = float(total), float(spread or 0)
        rows.append({"game": f"{away.get('team', {}).get('abbreviation', '—')} @ {home.get('team', {}).get('abbreviation', '—')}", "total": total, "away_implied": total / 2 + spread / 2 if total is not None else None, "home_implied": total / 2 - spread / 2 if total is not None else None})
    return pd.DataFrame(rows)
