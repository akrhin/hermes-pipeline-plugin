"""Unit tests for pipeline state module."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import state


class TestStateIsoToTs:
    def test_roundtrip(self):
        """A timestamp stored and loaded should be approximately equal."""
        now = time.time()
        iso = state._now_iso()
        back = state._iso_to_ts(iso)
        # Within 1 second of UTC (stored time may differ by a few milliseconds)
        assert abs(now - back) < 2.0

    def test_known_value(self):
        ts = state._iso_to_ts("2026-07-18T10:00:00")
        assert ts > 1_700_000_000


class TestStateSaveLoad:
    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.orig_path = state.STATE_PATH
        state.STATE_PATH = os.path.join(self.tmpdir, "test_state.json")

    def teardown_method(self):
        state.STATE_PATH = self.orig_path
        if os.path.exists(self.tmpdir):
            import shutil
            shutil.rmtree(self.tmpdir)

    def test_save_and_load(self):
        data = {"request": "test", "status": "running"}
        state.save(data)
        loaded = state.load()
        assert loaded is not None
        assert loaded["request"] == "test"
        assert loaded["status"] == "running"
        assert "created_at" in loaded
        assert "updated_at" in loaded

    def test_load_nonexistent(self):
        state.STATE_PATH = "/nonexistent/state.json"
        loaded = state.load()
        assert loaded is None

    def test_load_corrupted(self):
        with open(state.STATE_PATH, "w") as f:
            f.write("not json")
        loaded = state.load()
        assert loaded is None

    def test_clear_removes_state(self):
        data = {"request": "test"}
        state.save(data)
        assert os.path.exists(state.STATE_PATH)
        state.clear()
        assert not os.path.exists(state.STATE_PATH)

    def test_expired_state_returns_none(self):
        """State with timestamp older than TTL returns None."""
        data = {"request": "test", "status": "running"}
        state.save(data)
        # Manually set updated_at far in the past
        state_old = {
            "request": "test",
            "status": "running",
            "updated_at": "2020-01-01T00:00:00",
        }
        with open(state.STATE_PATH, "w") as f:
            json.dump(state_old, f)
        loaded = state.load()
        assert loaded is None


class TestConvergence:
    """Tests for converge logic — deterministic, no LLM."""

    def test_converged_no_findings(self):
        """Zero findings → converged."""
        state_obj = {"round": 0, "findings": []}
        result = state.evaluate_convergence(state_obj)
        assert result["decision"] == "converged"
        assert result["p0_count"] == 0
        assert result["p1_count"] == 0

    def test_converged_p2_only(self):
        """Only P2 findings → converged (advisories only)."""
        state_obj = {
            "round": 0,
            "findings": [
                {"severity": "P2", "file": "x.py", "category": "style"},
            ],
        }
        result = state.evaluate_convergence(state_obj)
        assert result["decision"] == "converged"
        assert result["p2_count"] == 1

    def test_continue_with_p0(self):
        """P0 findings within max rounds → continue."""
        state_obj = {
            "round": 0,
            "findings": [
                {"severity": "P0", "file": "x.py", "category": "security"},
            ],
        }
        result = state.evaluate_convergence(state_obj)
        assert result["decision"] == "continue"
        assert result["p0_count"] == 1

    def test_maxed_out(self):
        """Round >= max_rounds → maxed_out regardless of findings."""
        state_obj = {
            "round": 3,
            "max_rounds": 3,
            "findings": [
                {"severity": "P0", "file": "x.py", "category": "security"},
            ],
        }
        result = state.evaluate_convergence(state_obj)
        assert result["decision"] == "maxed_out"

    def test_stuck_same_fingerprint(self):
        """Same P0/P1 fingerprint as prev round → stuck."""
        state_obj = {
            "round": 2,
            "findings": [
                {"severity": "P0", "file": "x.py", "category": "security",
                 "description": "XSS in login"},
            ],
            "prev_findings_fingerprint": state._compute_fingerprint([
                {"severity": "P0", "file": "x.py", "category": "security",
                 "description": "XSS in login"},
            ]),
        }
        result = state.evaluate_convergence(state_obj)
        assert result["decision"] == "stuck"

    def test_not_stuck_different_fingerprint(self):
        """Different findings than previous round → continue."""
        # Round 1 findings
        fp = state._compute_fingerprint([
            {"severity": "P0", "file": "x.py", "category": "security", "description": "Old bug"},
        ])
        state_obj = {
            "round": 2,
            "findings": [
                {"severity": "P0", "file": "y.py", "category": "security",
                 "description": "New bug"},
            ],
            "findings_fingerprint": fp,
        }
        result = state.evaluate_convergence(state_obj)
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
        assert state._compute_fingerprint(a) == state._compute_fingerprint(b)

    def test_fingerprint_different(self):
        """Different findings produce different fingerprints."""
        a = [{"severity": "P0", "file": "a.py", "category": "sec", "description": "x"}]
        b = [{"severity": "P0", "file": "a.py", "category": "sec", "description": "y"}]
        assert state._compute_fingerprint(a) != state._compute_fingerprint(b)

    def test_save_preserves_convergence_fields(self):
        """save() should auto-add convergence fields with defaults."""
        data = {"request": "test", "status": "running"}
        state.save(data)
        loaded = state.load()
        assert loaded is not None
        assert "round" in loaded
        assert loaded["round"] == 0
        assert "max_rounds" in loaded
        assert loaded["max_rounds"] == 3
        assert "findings" in loaded
        assert loaded["findings"] == []
        assert "convergence" in loaded
        assert loaded["convergence"] == "running"
