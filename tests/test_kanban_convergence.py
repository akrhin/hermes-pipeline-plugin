"""
Unit tests for Kanban-native pipeline convergence (moved from state.py).

Tests the deterministic convergence logic that used to live in state.py
and is now in kanban.py.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import kanban as kb


class TestConvergence:
    """Tests for converge logic — deterministic, no LLM."""

    def test_converged_no_findings(self):
        """Zero findings → converged."""
        state = {"round": 0, "findings": []}
        result = kb.evaluate_convergence(state)
        assert result["decision"] == "converged"
        assert result["p0_count"] == 0
        assert result["p1_count"] == 0

    def test_converged_p2_only(self):
        """Only P2 findings → converged (advisories only)."""
        state = {
            "round": 0,
            "findings": [
                {"severity": "P2", "file": "x.py", "category": "style"},
            ],
        }
        result = kb.evaluate_convergence(state)
        assert result["decision"] == "converged"
        assert result["p2_count"] == 1

    def test_continue_with_p0(self):
        """P0 findings within max rounds → continue."""
        state = {
            "round": 0,
            "findings": [
                {"severity": "P0", "file": "x.py", "category": "security"},
            ],
        }
        result = kb.evaluate_convergence(state)
        assert result["decision"] == "continue"
        assert result["p0_count"] == 1

    def test_maxed_out(self):
        """Round >= max_rounds → maxed_out regardless of findings."""
        state = {
            "round": 3,
            "max_rounds": 3,
            "findings": [
                {"severity": "P0", "file": "x.py", "category": "security"},
            ],
        }
        result = kb.evaluate_convergence(state)
        assert result["decision"] == "maxed_out"

    def test_stuck_same_fingerprint(self):
        """Same P0/P1 fingerprint as prev round → stuck."""
        state = {
            "round": 2,
            "findings": [
                {"severity": "P0", "file": "x.py", "category": "security",
                 "description": "XSS in login"},
            ],
            "prev_findings_fingerprint": kb._compute_fingerprint([
                {"severity": "P0", "file": "x.py", "category": "security",
                 "description": "XSS in login"},
            ]),
        }
        result = kb.evaluate_convergence(state)
        assert result["decision"] == "stuck"

    def test_not_stuck_different_fingerprint(self):
        """Different findings than previous round → continue."""
        fp = kb._compute_fingerprint([
            {"severity": "P0", "file": "x.py", "category": "security",
             "description": "Old bug"},
        ])
        state = {
            "round": 2,
            "findings": [
                {"severity": "P0", "file": "y.py", "category": "security",
                 "description": "New bug"},
            ],
            "findings_fingerprint": fp,
        }
        result = kb.evaluate_convergence(state)
        assert result["decision"] == "continue"

    def test_fingerprint_consistency(self):
        """Same findings produce same fingerprint regardless of order."""
        a = [
            {"severity": "P0", "file": "b.py", "category": "sec", "description": "x"},
            {"severity": "P0", "file": "a.py", "category": "sec", "description": "y"},
        ]
        b = [
            {"severity": "P0", "file": "a.py", "category": "sec", "description": "y"},
            {"severity": "P0", "file": "b.py", "category": "sec", "description": "x"},
        ]
        assert kb._compute_fingerprint(a) == kb._compute_fingerprint(b)

    def test_fingerprint_different(self):
        """Different findings produce different fingerprints."""
        a = [{"severity": "P0", "file": "a.py", "category": "sec", "description": "x"}]
        b = [{"severity": "P0", "file": "a.py", "category": "sec", "description": "y"}]
        assert kb._compute_fingerprint(a) != kb._compute_fingerprint(b)
