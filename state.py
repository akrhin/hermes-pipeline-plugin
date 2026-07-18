"""
Convergence-aware state persistence for Pipeline Plugin.

Stores pipeline state as JSON in the plugin directory.
Supports lifecycle: running → converged|stuck|maxed_out|paused|done.
Auto-expiry: state older than 24h is considered stale.

Convergence logic (deterministic, no LLM):
  1. max_rounds reached          → maxed_out
  2. zero P0/P1 findings          → converged
  3. same P0/P1 fingerprint x2    → stuck
  4. else                          → continue (next round)
"""

import hashlib
import json
import os
import time
from calendar import timegm

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_PATH = os.path.join(PLUGIN_DIR, "state.json")
STATE_TTL_SECONDS = 24 * 3600  # 24 hours
MAX_CONVERGENCE_ROUNDS = 3


def save(state: dict) -> None:
    """Persist pipeline state to disk. Overwrites previous state."""
    state["updated_at"] = _now_iso()
    if "created_at" not in state:
        state["created_at"] = _now_iso()
    # Ensure convergence fields have defaults
    state.setdefault("round", 0)
    state.setdefault("max_rounds", MAX_CONVERGENCE_ROUNDS)
    state.setdefault("findings", [])
    state.setdefault("findings_fingerprint", "")
    state.setdefault("prev_findings_fingerprint", "")
    state.setdefault("convergence", "running")
    try:
        with open(STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except (OSError, PermissionError) as e:
        raise RuntimeError(f"Cannot save state to {STATE_PATH}: {e}") from e


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


def evaluate_convergence(state: dict) -> dict:
    """
    Evaluate pipeline convergence using deterministic criteria (no LLM).

    Returns:
    {
        "decision": "continue" | "converged" | "stuck" | "maxed_out",
        "reason": "human-readable explanation",
        "round": int,
        "p0_count": int,
        "p1_count": int,
        "p2_count": int,
    }
    """
    findings = state.get("findings", [])
    round_num = state.get("round", 0)
    max_rounds = state.get("max_rounds", MAX_CONVERGENCE_ROUNDS)

    # Count by severity
    p0 = [f for f in findings if f.get("severity") == "P0"]
    p1 = [f for f in findings if f.get("severity") == "P1"]
    p2 = [f for f in findings if f.get("severity") == "P2"]

    # Hard stop 1: max rounds
    if round_num >= max_rounds:
        return {
            "decision": "maxed_out",
            "reason": f"Reached max rounds ({max_rounds}) — "
                      f"{len(p0)} P0, {len(p1)} P1 findings unresolved",
            "round": round_num,
            "p0_count": len(p0),
            "p1_count": len(p1),
            "p2_count": len(p2),
        }

    # No P0/P1 findings → converged
    p0p1_findings = list(p0) + list(p1)
    if not p0p1_findings:
        return {
            "decision": "converged",
            "reason": f"No P0/P1 findings ({len(p2)} P2 advisories)",
            "round": round_num,
            "p0_count": 0,
            "p1_count": 0,
            "p2_count": len(p2),
        }

    # Compute fingerprint for this round's P0/P1 findings
    current_fp = _compute_fingerprint(p0p1_findings)
    prev_fp = state.get("prev_findings_fingerprint", "")

    # Stuck detection: same P0/P1 fingerprint as previous round
    if current_fp and current_fp == prev_fp:
        return {
            "decision": "stuck",
            "reason": f"Same {len(p0p1_findings)} P0/P1 findings as previous round — "
                      "fixes are not converging",
            "round": round_num,
            "p0_count": len(p0),
            "p1_count": len(p1),
            "p2_count": len(p2),
        }

    # Continue to next round
    return {
        "decision": "continue",
        "reason": f"{len(p0p1_findings)} P0/P1 findings remain — "
                  f"round {round_num + 1}/{max_rounds}",
        "round": round_num,
        "p0_count": len(p0),
        "p1_count": len(p1),
        "p2_count": len(p2),
    }


def _compute_fingerprint(findings: list) -> str:
    """Hash P0/P1 findings for stuck detection. Same findings = same hash."""
    if not findings:
        return ""
    items = sorted(
        f"{f.get('severity', '')}:{f.get('file', '')}:"
        f"{f.get('category', '')}:{f.get('description', '')[:80]}"
        for f in findings
    )
    return hashlib.md5("|".join(items).encode()).hexdigest()[:12]


def _now_iso() -> str:
    """Return current time as ISO string in UTC."""
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())


def _iso_to_ts(iso_str: str) -> float:
    """Parse UTC ISO string to Unix timestamp (seconds since epoch)."""
    return timegm(time.strptime(iso_str, "%Y-%m-%dT%H:%M:%S"))
