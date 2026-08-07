"""Small, reliable public-data adapter for LaunchCast.

This intentionally replaces the former 5,000-line fetch layer.  It has a
single job: give the UI a normalized live slate from MLB Stats API and Baseball
Savant, and raise useful errors when a provider is unavailable.
"""
from __future__ import annotations

from datetime import date
import io
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FutureTimeout

import pandas as pd
import requests
import streamlit as st
from park_factors import get_park, get_park_hand_factor
from weather import fetch_weather, hr_multiplier

HEADERS = {"User-Agent": "LaunchCast/1.0 (+public-data-dashboard)", "Accept": "application/json, text/csv, */*"}
TIMEOUT = 20
LINEUP_TIMEOUT = 8  # shorter timeout per lineup call


def _get(url: str, timeout: int = TIMEOUT) -> requests.Response:
    response = requests.get(url, headers=HEADERS, timeout=timeout)
    response.raise_for_status()
    return response


@st.cache_data(ttl=300, show_spinner=False)
def get_slate(game_date: str | None = None) -> pd.DataFrame:
    """Scheduled MLB games, excluding games MLB has cancelled or postponed."""
    game_date = game_date or date.today().isoformat()
    payload = _get("https://statsapi.mlb.com/api/v1/schedule?"
                   f"sportId=1&date={game_date}&hydrate=probablePitcher,team").json()
    rows = []
    for day in payload.get("dates", []):
        for game in day.get("games", []):
            status = game.get("status", {}).get("detailedState", "")
            if status.lower().startswith(("postponed", "cancelled", "canceled", "forfeit")):
                continue
            away, home = game["teams"]["away"], game["teams"]["home"]
            rows.append({
                "game_pk": game["gamePk"], "game_time": game.get("gameDate"), "status": status,
                "venue": game.get("venue", {}).get("name", "—"),
                "away_team": away["team"].get("abbreviation", away["team"]["name"][:3].upper()),
                "home_team": home["team"].get("abbreviation", home["team"]["name"][:3].upper()),
                "away_team_id": away["team"]["id"], "home_team_id": home["team"]["id"],
                "away_pitcher": (away.get("probablePitcher") or {}).get("fullName", "TBD"),
                "home_pitcher": (home.get("probablePitcher") or {}).get("fullName", "TBD"),
                "away_pitcher_id": (away.get("probablePitcher") or {}).get("id"),
                "home_pitcher_id": (home.get("probablePitcher") or {}).get("id"),
            })
    return pd.DataFrame(rows)


@st.cache_data(ttl=180, show_spinner=False)
def get_lineup(game_pk: int, side: str) -> list[dict]:
    """Confirmed batting order when posted; empty means it is not available."""
    try:
        payload = _get(f"https://statsapi.mlb.com/api/v1.1/game/{game_pk}/feed/live", timeout=LINEUP_TIMEOUT).json()
    except Exception:
        return []
    team = payload.get("liveData", {}).get("boxscore", {}).get("teams", {}).get(side, {})
    players, order = team.get("players", {}), team.get("battingOrder", [])
    return [{
        "player_id": person.get("id"), "player_name": person.get("fullName"),
        "bats": item.get("batSide", {}).get("code", "—"), "lineup_pos": index + 1,
    } for index, player_id in enumerate(order)
      if (item := players.get(f"ID{player_id}", {})) and (person := item.get("person", {}))]


@st.cache_data(ttl=900, show_spinner=False)
def get_team_roster(team_id: int) -> list[dict]:
    """Active non-pitchers, used only as an explicitly labelled pre-lineup fallback."""
    try:
        payload = _get(f"https://statsapi.mlb.com/api/v1/teams/{team_id}/roster/active?hydrate=person", timeout=LINEUP_TIMEOUT).json()
    except Exception:
        return []
    rows = []
    for item in payload.get("roster", []):
        if item.get("position", {}).get("type") == "Pitcher":
            continue
        person = item.get("person", {})
        rows.append({"player_id": person.get("id"), "player_name": person.get("fullName"),
                     "bats": ((person.get("batSide") or {}).get("code") or (item.get("batSide") or {}).get("code") or "—"), "lineup_pos": pd.NA})
    return rows


@st.cache_data(ttl=3600, show_spinner=False)
def get_hitter_stats(season: int) -> pd.DataFrame:
    """Season Statcast power signals in a stable, app-facing schema."""
    fields = "player_id,pa,iso,barrel_batted_rate,hard_hit_percent,launch_speed,flyballs_percent,home_run"
    url = ("https://baseballsavant.mlb.com/leaderboard/custom?"
           f"year={season}&type=batter&filter=&min=1&selections={fields}&chart=false&x=pa&y=pa&r=no&csv=true")
    try:
        df = pd.read_csv(io.StringIO(_get(url).text))
    except Exception as exc:
        raise ConnectionError(f"Baseball Savant batter leaderboard failed: {exc}")

    if df.empty or len(df.columns) < 3:
        raise ConnectionError("Baseball Savant returned empty or malformed hitter data")

    name_col = next((c for c in df.columns if c.lower() in ("last_name, first_name", "player_name", "name")), None)
    if name_col == "last_name, first_name":
        df["player_name"] = df[name_col].astype(str).map(
            lambda value: " ".join(reversed([x.strip() for x in value.split(",")])) if "," in value else value
        )
    elif name_col:
        df["player_name"] = df[name_col]
    else:
        df["player_name"] = "Unknown"

    aliases = {"barrel_batted_rate": "barrel_pct", "hard_hit_percent": "hard_hit", "launch_speed": "avg_ev", "flyballs_percent": "fb_pct"}
    df = df.rename(columns=aliases)
    for column in ["player_id", "pa", "barrel_pct", "hard_hit", "iso", "avg_ev", "fb_pct", "home_run"]:
        if column in df:
            df[column] = pd.to_numeric(df[column], errors="coerce")
    keep = [c for c in ["player_id", "player_name", "pa", "barrel_pct", "hard_hit", "iso", "avg_ev", "fb_pct", "home_run"] if c in df]
    return df[keep].dropna(subset=["player_id"])


@st.cache_data(ttl=3600, show_spinner=False)
def get_pitcher_stats(season: int) -> pd.DataFrame:
    """Pitcher HR/9 from Statcast outcomes; only qualified source rows are used."""
    fields = "player_id,home_run,pa"
    url = ("https://baseballsavant.mlb.com/leaderboard/custom?"
           f"year={season}&type=pitcher&filter=&min=1&selections={fields}&chart=false&x=pa&y=pa&r=no&csv=true")
    try:
        df = pd.read_csv(io.StringIO(_get(url).text))
    except Exception as exc:
        raise ConnectionError(f"Baseball Savant pitcher leaderboard failed: {exc}")

    df["player_id"] = pd.to_numeric(df.get("player_id"), errors="coerce")
    # PA / 4.3 is a transparent IP estimate when an official IP endpoint is not involved.
    df["pitcher_hr9"] = (pd.to_numeric(df.get("home_run"), errors="coerce") * 9 / (pd.to_numeric(df.get("pa"), errors="coerce") / 4.3).replace(0, pd.NA)).clip(0, 6)
    return df[["player_id", "pitcher_hr9"]].dropna(subset=["player_id"])


@st.cache_data(ttl=300, show_spinner=False)
def build_live_slate(game_date: str) -> tuple[pd.DataFrame, str]:
    """Join today's confirmed lineups (or labelled active-roster fallback) to power stats."""
    schedule = get_slate(game_date)
    if schedule.empty:
        return pd.DataFrame(), "No MLB games are scheduled for this date."

    hitters = get_hitter_stats(pd.Timestamp(game_date).year)
    pitchers = get_pitcher_stats(pd.Timestamp(game_date).year)

    rows, confirmed_sides = [], 0
    for game in schedule.to_dict("records"):
        for side, team_key, opp_key, pitcher_key, pitcher_id_key in [
            ("away", "away_team", "home_team", "home_pitcher", "home_pitcher_id"),
            ("home", "home_team", "away_team", "away_pitcher", "away_pitcher_id"),
        ]:
            try:
                lineup = get_lineup(game["game_pk"], side)
            except Exception:
                lineup = []
            confirmed = bool(lineup)
            if confirmed:
                confirmed_sides += 1
            else:
                lineup = get_team_roster(game[f"{side}_team_id"])
            for person in lineup:
                rows.append({**person, "team": game[team_key], "opponent": game[opp_key],
                             "game": f"{game['away_team']} @ {game['home_team']}", "opp_pitcher": game[pitcher_key],
                             "opp_pitcher_id": game[pitcher_id_key], "lineup_confirmed": confirmed,
                             "is_bench": not confirmed,
                             "start_time": game["game_time"], "venue": game["venue"]})

    base = pd.DataFrame(rows)
    if base.empty:
        return base, "Games found, but no active rosters were returned."

    base["player_id"] = pd.to_numeric(base["player_id"], errors="coerce")
    base["opp_pitcher_id"] = pd.to_numeric(base["opp_pitcher_id"], errors="coerce")
    out = base.merge(hitters, on="player_id", how="left", suffixes=("", "_stat"))
    if "player_name_stat" in out:
        out["player_name"] = out["player_name"].fillna(out["player_name_stat"])
    out = out.merge(pitchers.rename(columns={"player_id": "opp_pitcher_id"}), on="opp_pitcher_id", how="left")

    # Fetch weather once per venue; unavailable weather stays explicitly neutral.
    venue_context = {}
    venue_times = list(base[["venue", "start_time"]].drop_duplicates().itertuples(index=False, name=None))

    def load_venue_context(venue: str, start_time: str) -> tuple[str, tuple[float, str]]:
        park = get_park(venue)
        try:
            weather = fetch_weather(park["lat"], park["lon"], str(start_time)) if park["lat"] is not None else {}
            return venue, hr_multiplier(weather, park["cf_bearing"], park["roof"])
        except Exception:
            return venue, (1.0, "Weather unavailable")

    # Parallel calls prevent one delayed venue from serially holding up every
    # other game on a full slate. Cap workers and add per-future timeout.
    max_workers = min(6, len(venue_times)) if venue_times else 1
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(load_venue_context, venue, start): (venue, start) for venue, start in venue_times}
        for future in as_completed(futures):
            try:
                venue, context = future.result(timeout=10)
                venue_context[venue] = context
            except Exception:
                venue, _ = futures[future]
                venue_context[venue] = (1.0, "Weather unavailable")

    out["park_factor"] = [get_park_hand_factor(venue, bats) for venue, bats in zip(out["venue"], out["bats"])]
    out["weather_boost"] = out["venue"].map(lambda v: venue_context.get(v, (1.0, "Weather unavailable"))[0])
    out["weather_note"] = out["venue"].map(lambda v: venue_context.get(v, (1.0, "Weather unavailable"))[1])
    out["env_boost"] = (out["park_factor"] * out["weather_boost"]).round(2)
    out["recent_hr"] = pd.NA  # placeholder until a rolling endpoint is wired
    return out, f"Live slate · {confirmed_sides} confirmed lineups · {len(out)} hitters"
