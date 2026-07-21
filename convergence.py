"""Convergence engine for Pipeline Plugin.

Extracted from kanban.py to reduce module size (1014→~900 lines).
Deterministic evaluation of findings — no LLM calls.
"""

from __future__ import annotations

import hashlib
import logging

logger = logging.getLogger(__name__)

MAX_CONVERGENCE_ROUNDS = 3

# ── Filters ──────────────────────────────────────────────────────────────────

_CLOSED_STATUSES = frozenset({"fixed", "accepted", "none"})
_RELEVANT_SEVERITIES = frozenset({"P0", "P1"})


def _is_open(f: dict) -> bool:
    """True if a finding is still open (not fixed/accepted/none)."""
    return f.get("status", "open") not in _CLOSED_STATUSES


def _is_severe(f: dict) -> bool:
    """True if a finding is P0 or P1."""
    return f.get("severity") in _RELEVANT_SEVERITIES


# ── Fingerprint ──────────────────────────────────────────────────────────────


def _compute_fingerprint(findings: list) -> str:
    """Hash P0/P1 findings for stuck detection. Same findings = same hash."""
    if not findings:
        return ""
    items = sorted(
        f"{f.get('severity', '')}:{f.get('file', '')}:"
        f"{f.get('category', '')}:{(f.get('description') or '')[:80]}"
        for f in findings
    )
    return hashlib.md5("|".join(items).encode(), usedforsecurity=False).hexdigest()[:12]


# ── State mutation ───────────────────────────────────────────────────────────


def _update_convergence_state(state: dict, findings: list | None) -> None:
    """Mutate state in-place: store findings, compute fingerprint, increment round."""
    if findings is None:
        return
    curr_fp = state.get("findings_fingerprint", "")
    state["findings"] = findings
    severe_open = [f for f in findings if _is_severe(f) and _is_open(f)]
    state["findings_fingerprint"] = _compute_fingerprint(severe_open)
    state["prev_findings_fingerprint"] = curr_fp
    state["round"] = state.get("round", 0) + 1


# ── Query (pure) ─────────────────────────────────────────────────────────────


def _count_convergence_findings(state: dict) -> dict:
    """Count open findings by severity. Pure query — no mutation."""
    active = state.get("findings", [])
    p0 = [f for f in active if f.get("severity") == "P0" and _is_open(f)]
    p1 = [f for f in active if f.get("severity") == "P1" and _is_open(f)]
    p2 = [f for f in active if f.get("severity") == "P2"]
    return {
        "p0": p0,
        "p1": p1,
        "p2": p2,
        "p0_count": len(p0),
        "p1_count": len(p1),
        "p2_count": len(p2),
    }


def _evaluate_convergence_decision(
    round_num: int,
    max_rounds: int,
    p0_count: int,
    p1_count: int,
    p2_count: int,
    current_fp: str,
    prev_fp: str,
) -> dict:
    """Pure decision logic — no I/O, no mutations."""
    if p0_count == 0 and p1_count == 0:
        return {
            "decision": "converged",
            "reason": f"No P0/P1 findings ({p2_count} P2 advisories)",
            "round": round_num,
            "p0_count": 0,
            "p1_count": 0,
            "p2_count": p2_count,
        }

    if round_num >= max_rounds:
        return {
            "decision": "maxed_out",
            "reason": f"Reached max rounds ({max_rounds}) — "
                       f"{p0_count} P0, {p1_count} P1 unresolved",
            "round": round_num,
            "p0_count": p0_count,
            "p1_count": p1_count,
            "p2_count": p2_count,
        }

    if current_fp and current_fp == prev_fp:
        return {
            "decision": "stuck",
            "reason": f"Same {p0_count + p1_count} P0/P1 findings as previous round — "
            "fixes are not converging",
            "round": round_num,
            "p0_count": p0_count,
            "p1_count": p1_count,
            "p2_count": p2_count,
        }

    return {
        "decision": "continue",
        "reason": f"{p0_count + p1_count} P0/P1 findings remain — round {round_num}/{max_rounds}",
        "round": round_num,
        "p0_count": p0_count,
        "p1_count": p1_count,
        "p2_count": p2_count,
    }


# ── Public API (unchanged signature) ─────────────────────────────────────────


def evaluate_convergence(state: dict, findings: list | None = None) -> dict:
    """Evaluate pipeline convergence deterministically (no LLM).

    Only findings with status=open (or no status) count toward P0/P1.
    Findings with status='fixed', 'accepted', 'none' are ignored.
    Returns dict with decision/reason/counts.
    """
    # Normalize empty list to None to avoid unnecessary state mutation
    if findings is not None and len(findings) == 0:
        findings = None
    # 1. Mutate state
    _update_convergence_state(state, findings)

    # 1b. If findings were already in state (no new findings arg) but
    #     findings_fingerprint is missing, compute it now so stuck detection works.
    if findings is None and state.get("findings") and not state.get("findings_fingerprint"):
        severe_open = [f for f in state["findings"] if _is_severe(f) and _is_open(f)]
        state["findings_fingerprint"] = _compute_fingerprint(severe_open)

    # 2. Query
    counts = _count_convergence_findings(state)
    round_num = state.get("round", 0)
    max_rounds = state.get("max_rounds", MAX_CONVERGENCE_ROUNDS)
    current_fp = state.get("findings_fingerprint", "")
    prev_fp = state.get("prev_findings_fingerprint", "")

    # 3. Decide (pure)
    return _evaluate_convergence_decision(
        round_num=round_num,
        max_rounds=max_rounds,
        p0_count=counts["p0_count"],
        p1_count=counts["p1_count"],
        p2_count=counts["p2_count"],
        current_fp=current_fp,
        prev_fp=prev_fp,
    )
