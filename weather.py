"""Open-Meteo game-time weather adapter; no key required."""
from __future__ import annotations
import math
import pandas as pd
import requests
import streamlit as st

@st.cache_data(ttl=1800, show_spinner=False)
def fetch_weather(lat: float, lon: float, game_time: str) -> dict:
    target = pd.to_datetime(game_time, utc=True, errors="coerce")
    if pd.isna(target): return {}
    r = requests.get("https://api.open-meteo.com/v1/forecast", params={"latitude": lat, "longitude": lon, "hourly": "temperature_2m,wind_speed_10m,wind_direction_10m,precipitation_probability", "temperature_unit": "fahrenheit", "wind_speed_unit": "mph", "timezone": "UTC"}, timeout=15)
    r.raise_for_status(); hourly = r.json().get("hourly", {})
    times = pd.to_datetime(hourly.get("time", []), utc=True, errors="coerce")
    if len(times) == 0: return {}
    i = int(abs(times - target).argmin())
    return {"temp_f": hourly.get("temperature_2m", [None])[i], "wind_mph": hourly.get("wind_speed_10m", [None])[i], "wind_dir_deg": hourly.get("wind_direction_10m", [None])[i], "rain_pct": hourly.get("precipitation_probability", [None])[i]}

def hr_multiplier(weather: dict, cf_bearing: float | None = None, roof: str = "open") -> tuple[float, str]:
    if not weather or roof == "dome": return 1.0, "Indoor or weather unavailable"
    temp, wind = weather.get("temp_f"), weather.get("wind_mph") or 0
    mult, notes = 1.0, []
    if temp is not None:
        mult *= 1 + ((float(temp) - 70) / 10) * (.04 if temp >= 70 else .05); notes.append(f"{float(temp):.0f}°F")
    if cf_bearing is not None and weather.get("wind_dir_deg") is not None:
        outward = math.cos(math.radians((float(weather["wind_dir_deg"]) + 180) % 360 - cf_bearing))
        mult *= 1 + max(-.20, min(.20, outward * float(wind) * .01)); notes.append(f"{float(wind):.0f} mph wind")
    if weather.get("rain_pct", 0) and float(weather["rain_pct"]) >= 70: mult *= .94; notes.append("rain risk")
    return round(float(min(1.25, max(.78, mult))), 3), " · ".join(notes) or "Weather neutral"
