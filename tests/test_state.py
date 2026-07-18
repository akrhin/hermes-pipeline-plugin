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
