"""Edge-case tests for convergence.py — open/closed statuses, empty findings, mutations."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import convergence as cv


class TestIsOpen:
    """Tests for _is_open helper."""

    def test_open_default(self):
        """Finding without status is open."""
        assert cv._is_open({"severity": "P0", "file": "x.py"}) is True

    def test_open_explicit(self):
        assert cv._is_open({"severity": "P0", "status": "open"}) is True

    def test_fixed(self):
        assert cv._is_open({"severity": "P0", "status": "fixed"}) is False

    def test_accepted(self):
        assert cv._is_open({"severity": "P0", "status": "accepted"}) is False

    def test_none_status(self):
        assert cv._is_open({"severity": "P2", "status": "none"}) is False


class TestIsSevere:
    """Tests for _is_severe helper."""

    def test_p0_is_severe(self):
        assert cv._is_severe({"severity": "P0"}) is True

    def test_p1_is_severe(self):
        assert cv._is_severe({"severity": "P1"}) is True

    def test_p2_is_not_severe(self):
        assert cv._is_severe({"severity": "P2"}) is False

    def test_unknown_severity(self):
        assert cv._is_severe({"severity": "P3"}) is False

    def test_missing_severity(self):
        assert cv._is_severe({}) is False


class TestUpdateConvergenceState:
    """Tests for _update_convergence_state — state mutation."""

    def test_none_findings_does_not_mutate(self):
        state = {"round": 0}
        cv._update_convergence_state(state, None)
        assert state["round"] == 0
        assert "findings" not in state
        assert "findings_fingerprint" not in state

    def test_empty_findings_is_equivalent_to_none(self):
        """Empty list is normalized to None by evaluate_convergence."""
        state = {"round": 0}
        # _update_convergence_state itself doesn't normalize, so we call
        # evaluate_convergence instead
        result = cv.evaluate_convergence(state, [])
        assert result["decision"] == "converged"
        assert "findings" not in state or state["findings"] == []

    def test_mutates_round_and_fingerprint(self):
        state = {"round": 0}
        findings = [
            {"severity": "P0", "file": "x.py", "category": "sec", "description": "bug"}
        ]
        cv._update_convergence_state(state, findings)
        assert state["round"] == 1
        assert "findings_fingerprint" in state
        assert len(state["findings_fingerprint"]) > 0

    def test_stores_prev_findings_fingerprint(self):
        state = {"round": 0}
        f1 = [{"severity": "P0", "file": "a.py", "category": "sec", "description": "x"}]
        cv._update_convergence_state(state, f1)
        fp1 = state.get("findings_fingerprint")

        # Second call
        f2 = [{"severity": "P0", "file": "b.py", "category": "sec", "description": "y"}]
        cv._update_convergence_state(state, f2)
        fp2 = state.get("findings_fingerprint")

        assert state.get("prev_findings_fingerprint") == fp1
        assert fp1 != fp2


class TestCountConvergenceFindings:
    """Tests for _count_convergence_findings — pure query no mutation."""

    def test_empty_findings(self):
        counts = cv._count_convergence_findings({"findings": []})
        assert counts["p0_count"] == 0
        assert counts["p1_count"] == 0
        assert counts["p2_count"] == 0

    def test_only_fixed_findings_are_ignored(self):
        counts = cv._count_convergence_findings({
            "findings": [
                {"severity": "P0", "status": "fixed", "file": "x.py", "category": "sec"},
                {"severity": "P1", "status": "accepted", "file": "y.py", "category": "style"},
            ]
        })
        assert counts["p0_count"] == 0
        assert counts["p1_count"] == 0
        assert counts["p2_count"] == 0

    def test_mixed_findings(self):
        counts = cv._count_convergence_findings({
            "findings": [
                {"severity": "P0", "status": "open", "file": "a.py", "category": "sec"},
                {"severity": "P1", "status": "fixed", "file": "b.py", "category": "style"},
                {"severity": "P1", "status": "open", "file": "c.py", "category": "perf"},
                {"severity": "P2", "file": "d.py", "category": "docs"},
            ]
        })
        assert counts["p0_count"] == 1
        assert counts["p1_count"] == 1
        assert counts["p2_count"] == 1


class TestEvaluateConvergenceEdgeCases:
    """Edge cases for the public evaluate_convergence()."""

    def test_no_findings_converged(self):
        state = {"round": 0}
        result = cv.evaluate_convergence(state)
        assert result["decision"] == "converged"
        assert result["p0_count"] == 0

    def test_findings_already_in_state_no_new_arg(self):
        """When findings are already in state and no new arg given."""
        state = {"round": 0, "findings": [{"severity": "P0", "file": "x.py", "category": "sec"}]}
        result = cv.evaluate_convergence(state)
        assert result["decision"] in ("continue",)
        assert result["p0_count"] == 1

    def test_all_findings_fixed(self):
        """All findings are fixed/accepted → converged."""
        state = {"round": 0}
        findings = [
            {"severity": "P0", "status": "fixed", "file": "x.py", "category": "sec"},
            {"severity": "P1", "status": "accepted", "file": "y.py", "category": "style"},
        ]
        result = cv.evaluate_convergence(state, findings)
        assert result["decision"] == "converged"

    def test_converged_p2_only_no_status(self):
        """P2 findings without explicit status → converged (not severe)."""
        state = {"round": 0}
        findings = [
            {"severity": "P2", "file": "x.py", "category": "style", "description": "minor"},
        ]
        result = cv.evaluate_convergence(state, findings)
        assert result["decision"] == "converged"
        assert result["p2_count"] == 1

    def test_round_equals_max_rounds(self):
        """When round reaches max_rounds with P0 findings → maxed_out."""
        state = {"round": 3, "max_rounds": 3}
        # maxed_out only triggers on P0/P1 — add finding to make it non-trivial
        result = cv.evaluate_convergence(
            state,
            [{"severity": "P0", "file": "x.py", "category": "sec", "description": "bug"}],
        )
        assert result["decision"] == "maxed_out"

    def test_stuck_detected_across_calls(self):
        """Same fingerprint across two calls → stuck."""
        state = {"round": 0}
        findings = [
            {"severity": "P0", "file": "x.py", "category": "sec", "description": "same"},
        ]
        cv.evaluate_convergence(state, findings)
        result = cv.evaluate_convergence(state, findings)
        assert result["decision"] == "stuck"

    def test_fingerprint_stability_independent_of_description_order(self):
        """Fingerprint should not depend on finding order within a round."""
        findings_a = [
            {"severity": "P0", "file": "b.py", "category": "sec", "description": "x"},
            {"severity": "P1", "file": "a.py", "category": "perf", "description": "y"},
        ]
        findings_b = [
            {"severity": "P1", "file": "a.py", "category": "perf", "description": "y"},
            {"severity": "P0", "file": "b.py", "category": "sec", "description": "x"},
        ]
        state_a = {"round": 0}
        state_b = {"round": 0}
        cv._update_convergence_state(state_a, findings_a)
        cv._update_convergence_state(state_b, findings_b)
        assert state_a["findings_fingerprint"] == state_b["findings_fingerprint"]

    def test_empty_findings_list_normalized_to_none(self):
        """Empty list should be treated same as None (no state mutation)."""
        state = {"round": 0}
        result = cv.evaluate_convergence(state, [])
        assert result["decision"] == "converged"
        assert state["round"] == 0  # not incremented


class TestDecisionPureFunction:
    """Direct tests for _evaluate_convergence_decision (pure, no mutations)."""

    def test_converged_no_p0_p1(self):
        result = cv._evaluate_convergence_decision(
            round_num=1, max_rounds=3,
            p0_count=0, p1_count=0, p2_count=2,
            current_fp="", prev_fp="",
        )
        assert result["decision"] == "converged"

    def test_maxed_out_over_limit(self):
        result = cv._evaluate_convergence_decision(
            round_num=3, max_rounds=3,
            p0_count=1, p1_count=0, p2_count=0,
            current_fp="abc", prev_fp="def",
        )
        assert result["decision"] == "maxed_out"

    def test_stuck_same_fingerprint(self):
        result = cv._evaluate_convergence_decision(
            round_num=2, max_rounds=3,
            p0_count=1, p1_count=1, p2_count=0,
            current_fp="abc123", prev_fp="abc123",
        )
        assert result["decision"] == "stuck"

    def test_continue_new_fingerprint(self):
        result = cv._evaluate_convergence_decision(
            round_num=1, max_rounds=3,
            p0_count=2, p1_count=0, p2_count=0,
            current_fp="abc123", prev_fp="def456",
        )
        assert result["decision"] == "continue"

    def test_continue_empty_fingerprints(self):
        """No previous state — still continue if P0/P1 exist."""
        result = cv._evaluate_convergence_decision(
            round_num=1, max_rounds=3,
            p0_count=2, p1_count=0, p2_count=0,
            current_fp="", prev_fp="",
        )
        assert result["decision"] == "continue"
