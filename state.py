"""
State persistence for Pipeline Plugin.

Stores pipeline state as JSON in the plugin directory.
Supports lifecycle: running → paused → done.
Auto-expiry: state older than 24h is considered stale.
"""

import calendar
import json
import os
import time

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_PATH = os.path.join(PLUGIN_DIR, "state.json")
STATE_TTL_SECONDS = 24 * 3600  # 24 hours


def save(state: dict) -> None:
    """Persist pipeline state to disk. Overwrites previous state."""
    state["updated_at"] = _now_iso()
    if "created_at" not in state:
        state["created_at"] = _now_iso()
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def load() -> dict | None:
    """Load persisted pipeline state. Returns None if missing or expired."""
    if not os.path.exists(STATE_PATH):
        return None

    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            state = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None

    # Check expiry — both stored and current time in UTC
    updated_at = state.get("updated_at", "")
    if updated_at:
        try:
            updated_ts = _iso_to_ts(updated_at)
            if time.time() - updated_ts > STATE_TTL_SECONDS:
                return None  # Expired
        except (ValueError, OSError):
            pass

    return state


def clear() -> None:
    """Remove persisted state file."""
    if os.path.exists(STATE_PATH):
        os.remove(STATE_PATH)


def _now_iso() -> str:
    """Return current time as ISO string in UTC."""
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())


def _iso_to_ts(iso_str: str) -> float:
    """Parse UTC ISO string to Unix timestamp (seconds since epoch)."""
    return calendar.timegm(time.strptime(iso_str, "%Y-%m-%dT%H:%M:%S"))
