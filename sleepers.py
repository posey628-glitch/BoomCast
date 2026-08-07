"""Today-vs-season sleeper discovery."""
from __future__ import annotations
import pandas as pd

def find_sleepers(frame: pd.DataFrame, min_pa: int = 100) -> pd.DataFrame:
    out = frame.copy()
    if out.empty or "hr_score" not in out:
        out["sleeper_score"], out["is_sleeper"] = pd.NA, False; return out
    today = pd.to_numeric(out["hr_score"], errors="coerce").rank(pct=True) * 100
    season = pd.to_numeric(out.get("home_run", pd.Series(index=out.index, dtype=float)), errors="coerce").rank(pct=True) * 100
    out["sleeper_score"] = (today - season).round(1)
    out.loc[pd.to_numeric(out.get("pa", pd.Series(index=out.index, dtype=float)), errors="coerce") < min_pa, "sleeper_score"] = pd.NA
    out["is_sleeper"] = out["sleeper_score"].ge(25).fillna(False)
    return out
