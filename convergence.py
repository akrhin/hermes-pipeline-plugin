"""Convergence engine for Pipeline Plugin.

Extracted from kanban.py to reduce module size (1014→~900 lines).
Deterministic evaluation of findings — no LLM calls.
"""

from __future__ import annotations

import hashlib
import logging

logger = logging.getLogger(__name__)

MAX_CONVERGENCE_ROUNDS = 3


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


def evaluate_convergence(state: dict, findings: list | None = None) -> dict:
    """Evaluate pipeline convergence deterministically (no LLM).

    Only findings with status=open (or no status) count toward P0/P1.
    Findings with status='fixed', 'accepted', 'none' are ignored.
    Returns dict with decision/reason/counts.
    """
    if findings is not None:
        curr_fp = state.get("findings_fingerprint", "")
        state["findings"] = findings
        state["findings_fingerprint"] = _compute_fingerprint(
            [
                f
                for f in findings
                if f.get("severity") in ("P0", "P1")
                and f.get("status", "open") not in ("fixed", "accepted", "none")
            ]
        )
        state["prev_findings_fingerprint"] = curr_fp
        state["round"] = state.get("round", 0) + 1

    active_findings = state.get("findings", [])
    round_num = state.get("round", 0)
    max_rounds = state.get("max_rounds", MAX_CONVERGENCE_ROUNDS)

    # Filter: only count findings that are actually open
    open_findings = [
        f for f in active_findings if f.get("status", "open") not in ("fixed", "accepted", "none")
    ]
    p0 = [f for f in open_findings if f.get("severity") == "P0"]
    p1 = [f for f in open_findings if f.get("severity") == "P1"]
    p2 = [f for f in active_findings if f.get("severity") == "P2"]
    p0p1 = list(p0) + list(p1)

    if not p0p1:
        return {
            "decision": "converged",
            "reason": f"No P0/P1 findings ({len(p2)} P2 advisories)",
            "round": round_num,
            "p0_count": 0,
            "p1_count": 0,
            "p2_count": len(p2),
        }

    if round_num >= max_rounds:
        return {
            "decision": "maxed_out",
            "reason": f"Reached max rounds ({max_rounds}) — {len(p0)} P0, {len(p1)} P1 unresolved",
            "round": round_num,
            "p0_count": len(p0),
            "p1_count": len(p1),
            "p2_count": len(p2),
        }

    current_fp = _compute_fingerprint(p0p1)
    prev_fp = state.get("prev_findings_fingerprint", "")
    if current_fp and current_fp == prev_fp:
        return {
            "decision": "stuck",
            "reason": f"Same {len(p0p1)} P0/P1 findings as previous round — "
            "fixes are not converging",
            "round": round_num,
            "p0_count": len(p0),
            "p1_count": len(p1),
            "p2_count": len(p2),
        }

    return {
        "decision": "continue",
        "reason": f"{len(p0p1)} P0/P1 findings remain — round {round_num}/{max_rounds}",
        "round": round_num,
        "p0_count": len(p0),
        "p1_count": len(p1),
        "p2_count": len(p2),
    }
