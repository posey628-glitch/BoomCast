"""Small, reliable public-data adapter for LaunchCast."""
from __future__ import annotations

from datetime import date
import io
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
import requests
import streamlit as st
from park_factors import get_park, get_park_hand_factor
from weather import fetch_weather, hr_multiplier

HEADERS = {"User-Agent": "LaunchCast/1.0 (+public-data-dashboard)", "Accept": "application/json, text/csv, */*"}
TIMEOUT = 20
LINEUP_TIMEOUT = 8


def _get(url: str, timeout: int = TIMEOUT) -> requests.Response:
    response = requests.get(url, headers=HEADERS, timeout=timeout)
    response.raise_for_status()
    return response


@st.cache_data(ttl=300, show_spinner=False)
def get_slate(game_date: str | None = None) -> pd.DataFrame:
    """Scheduled MLB games."""
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
            # Try to get pitcher hand; fallback to R
            away_pitcher_obj = away.get("probablePitcher") or {}
            home_pitcher_obj = home.get("probablePitcher") or {}
            away_hand = (away_pitcher_obj.get("pitchHand") or {}).get("code", "R")
            home_hand = (home_pitcher_obj.get("pitchHand") or {}).get("code", "R")
            rows.append({
                "game_pk": game["gamePk"], "game_time": game.get("gameDate"), "status": status,
                "venue": game.get("venue", {}).get("name", "—"),
                "away_team": away["team"].get("abbreviation", away["team"]["name"][:3].upper()),
                "home_team": home["team"].get("abbreviation", home["team"]["name"][:3].upper()),
                "away_team_id": away["team"]["id"], "home_team_id": home["team"]["id"],
                "away_pitcher": away_pitcher_obj.get("fullName", "TBD"),
                "home_pitcher": home_pitcher_obj.get("fullName", "TBD"),
                "away_pitcher_id": away_pitcher_obj.get("id"),
                "home_pitcher_id": home_pitcher_obj.get("id"),
                "away_pitcher_hand": away_hand,
                "home_pitcher_hand": home_hand,
            })
    return pd.DataFrame(rows)


@st.cache_data(ttl=180, show_spinner=False)
def get_lineup(game_pk: int, side: str) -> list[dict]:
    """Confirmed batting order when posted."""
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
    """Active non-pitchers fallback."""
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
    """Season Statcast power signals."""
    fields = "player_id,pa,iso,barrel_batted_rate,hard_hit_percent,launch_speed,flyballs_percent,home_run"
    url = ("https://baseballsavant.mlb.com/leaderboard/custom?"
           f"year={season}&type=batter&filter=&min=1&selections={fields}&chart=false&x=pa&y=pa&r=no&csv=true")
    try:
        df = pd.read_csv(io.StringIO(_get(url).text))
    except Exception as exc:
        raise ConnectionError(f"Savant batter failed: {exc}")
    if df.empty or len(df.columns) < 3:
        raise ConnectionError("Savant returned empty batter data")
    name_col = next((c for c in df.columns if c.lower() in ("last_name, first_name", "player_name", "name")), None)
    if name_col == "last_name, first_name":
        df["player_name"] = df[name_col].astype(str).map(lambda v: " ".join(reversed([x.strip() for x in v.split(",")])) if "," in v else v)
    elif name_col:
        df["player_name"] = df[name_col]
    else:
        df["player_name"] = "Unknown"
    aliases = {"barrel_batted_rate": "barrel_pct", "hard_hit_percent": "hard_hit", "launch_speed": "avg_ev", "flyballs_percent": "fb_pct"}
    df = df.rename(columns=aliases)
    for col in ["player_id", "pa", "barrel_pct", "hard_hit", "iso", "avg_ev", "fb_pct", "home_run"]:
        if col in df:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    keep = [c for c in ["player_id", "player_name", "pa", "barrel_pct", "hard_hit", "iso", "avg_ev", "fb_pct", "home_run"] if c in df]
    return df[keep].dropna(subset=["player_id"])


@st.cache_data(ttl=3600, show_spinner=False)
def get_pitcher_stats(season: int) -> pd.DataFrame:
    """Pitcher HR/9 from Statcast."""
    fields = "player_id,home_run,pa"
    url = ("https://baseballsavant.mlb.com/leaderboard/custom?"
           f"year={season}&type=pitcher&filter=&min=1&selections={fields}&chart=false&x=pa&y=pa&r=no&csv=true")
    try:
        df = pd.read_csv(io.StringIO(_get(url).text))
    except Exception as exc:
        raise ConnectionError(f"Savant pitcher failed: {exc}")
    df["player_id"] = pd.to_numeric(df.get("player_id"), errors="coerce")
    df["pitcher_hr9"] = (pd.to_numeric(df.get("home_run"), errors="coerce") * 9 / (pd.to_numeric(df.get("pa"), errors="coerce") / 4.3).replace(0, pd.NA)).clip(0, 6)
    return df[["player_id", "pitcher_hr9"]].dropna(subset=["player_id"])


@st.cache_data(ttl=300, show_spinner=False)
def build_live_slate(game_date: str) -> tuple[pd.DataFrame, str]:
    """Join lineups to power stats."""
    schedule = get_slate(game_date)
    if schedule.empty:
        return pd.DataFrame(), "No MLB games scheduled."
    hitters = get_hitter_stats(pd.Timestamp(game_date).year)
    pitchers = get_pitcher_stats(pd.Timestamp(game_date).year)
    rows, confirmed_sides = [], 0
    for game in schedule.to_dict("records"):
        for side, team_key, opp_key, pitcher_key, pitcher_id_key, pitcher_hand_key in [
            ("away", "away_team", "home_team", "home_pitcher", "home_pitcher_id", "home_pitcher_hand"),
            ("home", "home_team", "away_team", "away_pitcher", "away_pitcher_id", "away_pitcher_hand"),
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
                             "game": f"{game['away_team']} @ {game['home_team']}",
                             "opp_pitcher": game[pitcher_key],
                             "opp_pitcher_id": game[pitcher_id_key],
                             "pitcher_hand": game.get(pitcher_hand_key, "R"),
                             "lineup_confirmed": confirmed,
                             "is_bench": not confirmed,
                             "start_time": game["game_time"], "venue": game["venue"]})
    base = pd.DataFrame(rows)
    if base.empty:
        return base, "Games found, but no rosters returned."
    base["player_id"] = pd.to_numeric(base["player_id"], errors="coerce")
    base["opp_pitcher_id"] = pd.to_numeric(base["opp_pitcher_id"], errors="coerce")
    out = base.merge(hitters, on="player_id", how="left", suffixes=("", "_stat"))
    if "player_name_stat" in out:
        out["player_name"] = out["player_name"].fillna(out["player_name_stat"])
    out = out.merge(pitchers.rename(columns={"player_id": "opp_pitcher_id"}), on="opp_pitcher_id", how="left")
    # Weather
    venue_context = {}
    venue_times = list(base[["venue", "start_time"]].drop_duplicates().itertuples(index=False, name=None))
    def load_venue_context(venue, start_time):
        park = get_park(venue)
        try:
            weather = fetch_weather(park["lat"], park["lon"], str(start_time)) if park["lat"] is not None else {}
            return venue, hr_multiplier(weather, park["cf_bearing"], park["roof"])
        except Exception:
            return venue, (1.0, "Weather unavailable")
    max_workers = min(6, len(venue_times)) if venue_times else 1
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(load_venue_context, v, t): (v, t) for v, t in venue_times}
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
    out["recent_hr"] = pd.NA
    return out, f"Live slate · {confirmed_sides} confirmed lineups · {len(out)} hitters"
