"""CSV input schema and aliases at the app boundary."""
from __future__ import annotations
import pandas as pd
ALIASES = {"player":"player_name", "name":"player_name", "opp":"opponent", "pitcher":"opp_pitcher", "hr9":"pitcher_hr9", "barrel_batted_rate":"barrel_pct", "hard_hit_percent":"hard_hit", "launch_speed":"avg_ev", "flyballs_percent":"fb_pct", "env_mult":"env_boost"}
def canonicalize(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy(); out.columns = [str(c).strip().lower().replace(" ", "_") for c in out.columns]
    return out.rename(columns={a: b for a, b in ALIASES.items() if a in out and b not in out})
def assert_schema(frame: pd.DataFrame) -> list[str]:
    return [f"Missing required column: {name}" for name in ("player_name", "team") if name not in frame.columns]
