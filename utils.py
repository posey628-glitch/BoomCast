"""
utils.py — BoomCast small pure utilities.

Extracted verbatim from app.py (mlb-hr-and-k v46.54). These are the defensive
type-coercion helpers used throughout the app — they exist because pandas NaN
is truthy, so naive `int(x)` / `(x or "").upper()` patterns crash on missing
data. Stateless, no Streamlit, no network.
"""
from typing import Optional
import pandas as pd


def safe_int(val) -> Optional[int]:
    try:
        if val is None or pd.isna(val):
            return None
    except (ValueError, TypeError):
        return None  # v45.14: array-like → pd.isna truthiness raises
    try:
        return int(val)
    except (ValueError, TypeError):
        return None



def safe_str(val) -> str:
    """v43.43 (crash fix): return value as str, or empty string if None/NaN.

    Replaces the unsafe pattern `(x or "").upper()` which crashes when x
    is float NaN (NaN is truthy in Python, so `nan or ""` returns nan,
    then .upper() fails with AttributeError).

    Use as: `safe_str(row.get("bats")).upper()`
    """
    if val is None:
        return ""
    try:
        if pd.isna(val):
            return ""
    except (TypeError, ValueError):
        # Some non-numeric values throw on pd.isna — treat as string
        pass
    return str(val)



def safe_float(val) -> Optional[float]:
    try:
        if val is None or pd.isna(val):
            return None
    except (ValueError, TypeError):
        return None  # v45.14: array-like → pd.isna truthiness raises
    try:
        return float(val)
    except (ValueError, TypeError):
        return None
