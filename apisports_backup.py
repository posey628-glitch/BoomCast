"""
apisports_backup.py — api-sports.io baseball as a BACKUP source for LaunchCast 2.0.

The MLB app's PRIMARY sources are MLB Stats API (statsapi) + Baseball Savant.
Those are authoritative but can rate-limit or change. This adds api-sports.io
(baseball) as a FALLBACK that only fires if a primary is unavailable, giving the
app a graceful degrade path instead of going dark.

api-sports free tier = 100 req/day SHARED across all sports, so this is called
ONLY as a fallback, never routinely. The MLB app already has a health-banner
system (_render_top_health_banner); this complements it with an actual backup.
"""
from __future__ import annotations


def _apisports_key():
    try:
        import streamlit as st
        for name in ("apinba_key", "apisports_key", "api_sports_key", "rapidapi_key"):
            v = st.secrets.get(name, "")
            if v:
                return str(v).strip().strip('"').strip("'")
    except Exception:
        pass
    return ""


def apisports_key_present() -> bool:
    return bool(_apisports_key())


def apisports_baseball_reachable() -> bool:
    """Light probe: is api-sports baseball reachable with the key? For the health
    panel — confirms the backup is available BEFORE it's ever needed."""
    import requests
    key = _apisports_key()
    if not key:
        return False
    try:
        r = requests.get("https://v1.baseball.api-sports.io/status",
                         headers={"x-apisports-key": key}, timeout=15)
        return r.status_code == 200
    except Exception:
        return False


def apisports_baseball_status() -> dict:
    """Returns the api-sports account status (requests used/remaining today) so
    you can SEE your quota — useful given the 100/day shared limit."""
    import requests
    key = _apisports_key()
    if not key:
        return {"available": False, "reason": "no key"}
    try:
        r = requests.get("https://v1.baseball.api-sports.io/status",
                         headers={"x-apisports-key": key}, timeout=15)
        if r.status_code == 200:
            data = r.json().get("response", {})
            reqs = (data.get("requests") or {})
            return {
                "available": True,
                "requests_used_today": reqs.get("current"),
                "daily_limit": reqs.get("limit_day"),
                "plan": (data.get("subscription") or {}).get("plan"),
            }
        return {"available": False, "reason": f"HTTP {r.status_code}"}
    except Exception as e:
        return {"available": False, "reason": f"{type(e).__name__}"}
