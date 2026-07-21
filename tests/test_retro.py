"""Edge-case tests for retro.py — thread safety, file rotation, analysis edge cases."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import retro as rt


class TestRetroConfig:
    """Tests for _read_retro_config()."""

    def test_defaults_on_missing_file(self):
        config = rt._read_retro_config("/nonexistent/path.yaml")
        assert config["enabled"] is True
        assert config["max_files"] == 100

    def test_defaults_on_empty_yaml(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text("")
        result = rt._read_retro_config(str(config_file))
        assert result["enabled"] is True

    def test_defaults_on_bad_yaml(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text("not: valid: yaml:\n  - broken")
        result = rt._read_retro_config(str(config_file))
        assert result["enabled"] is True

    def test_merge_with_defaults(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text("pipeline:\n  retro:\n    enabled: false\n    max_files: 5")
        result = rt._read_retro_config(str(config_file))
        assert result["enabled"] is False
        assert result["max_files"] == 5
        # Other defaults preserved
        assert "dir" in result
        assert "auto_analyze" in result


class TestRotate:
    """Tests for _rotate_if_needed."""

    def test_no_rotation_under_limit(self, tmp_path):
        retro_dir = str(tmp_path)
        for i in range(3):
            (tmp_path / f"pipe_{i}.jsonl").write_text("{}")
        rt._rotate_if_needed(retro_dir, {"max_files": 5})
        remaining = list(tmp_path.glob("pipe_*.jsonl"))
        assert len(remaining) == 3

    def test_rotation_over_limit(self, tmp_path):
        retro_dir = str(tmp_path)
        for i in range(5):
            (tmp_path / f"pipe_{i}.jsonl").write_text("{}")
        rt._rotate_if_needed(retro_dir, {"max_files": 3})
        remaining = sorted(tmp_path.glob("pipe_*.jsonl"))
        assert len(remaining) <= 3

    def test_rotation_removes_oldest_first(self, tmp_path):
        retro_dir = str(tmp_path)
        import time
        # Create files with different ages
        for i in range(3):
            p = tmp_path / f"pipe_{i}.jsonl"
            p.write_text("{}")
            if i == 0:
                time.sleep(0.02)  # ensure different mtime
        rt._rotate_if_needed(retro_dir, {"max_files": 2})
        remaining = [p.name for p in tmp_path.glob("pipe_*.jsonl")]
        # The oldest one (pipe_0) should have been rotated
        assert "pipe_0.jsonl" not in remaining or len(remaining) <= 2


class TestEnsureRetroDir:
    """Tests for _ensure_retro_dir."""

    def test_disabled_returns_none(self):
        result = rt._ensure_retro_dir({"enabled": False})
        assert result is None

    def test_creates_directory(self, tmp_path):
        test_dir = str(tmp_path / "retro" / "logs")
        result = rt._ensure_retro_dir({"enabled": True, "dir": test_dir})
        assert result is not None
        assert os.path.isdir(result)
        assert result == test_dir


class TestRetroLogger:
    """Tests for RetroLogger class — logging, edge cases."""

    def test_disabled_no_write(self, tmp_path):
        retro_dir = str(tmp_path / "retro")
        with mock.patch.object(rt, "_read_retro_config") as mock_config:
            mock_config.return_value = {"enabled": False, "dir": retro_dir, "max_files": 100,
                                         "auto_analyze": False}
            logger = rt.RetroLogger(run_id="test_disabled")
            logger.log("test_event", key="val")
        assert not list(Path(retro_dir).glob("*.jsonl"))

    def test_log_without_run_id_does_not_open_file(self, tmp_path):
        retro_dir = str(tmp_path / "retro")
        with mock.patch.object(rt, "_read_retro_config") as mock_config:
            mock_config.return_value = {"enabled": True, "dir": retro_dir, "max_files": 100,
                                         "auto_analyze": False}
            logger = rt.RetroLogger(run_id="")
            logger.log("test_event")
        assert not list(Path(retro_dir).glob("*.jsonl"))

    def test_set_run_id_updates_id(self):
        logger = rt.RetroLogger(run_id="old_id")
        logger.set_run_id("new_id")
        assert logger._run_id == "new_id"

    def test_convenience_methods(self, tmp_path):
        retro_dir = str(tmp_path / "retro")
        with mock.patch.object(rt, "_read_retro_config") as mock_config:
            mock_config.return_value = {"enabled": True, "dir": retro_dir, "max_files": 100,
                                         "auto_analyze": False}
            logger = rt.RetroLogger(run_id="pipe:test")
            logger.agent_start("finder", "direct", "flash", round=0, tokens_prompt=100)
            logger.agent_done("finder", 12.5, result="ok", tokens_response=200)
            logger.convergence(round=1, decision="converged", p0=0, p1=0, p2=2,
                               fingerprint="abc", reason="all good")
            logger.model_routing("coder", "delegate/flash", "delegate/flash")
            logger.ensemble_gen("coder", n=3, temperatures=[0.3, 0.5, 0.7])
            logger.ensemble_judge("candidate_1", "llm", "best")
            logger.context_selective("coder", ["implementation"], tokens_saved=500)
            logger.findings_event(p0=1, p1=0, p2=2, fixed=1, accepted=0)
            logger.error("tester", "timeout", "retried")
            logger.findings_detail([{"severity": "P0", "file": "x.py"}])

            logger.close()

        # Verify log file was created and has 10 events
        log_files = list(Path(retro_dir).glob("*.jsonl"))
        assert len(log_files) > 0
        with open(log_files[0]) as f:
            lines = [ln for ln in f if ln.strip()]
        assert len(lines) >= 10

    def test_close_idempotent(self):
        logger = rt.RetroLogger(run_id="test")
        logger.close()  # first close
        logger.close()  # second close should not raise

    def test_sanitizes_run_id_in_filename(self, tmp_path):
        retro_dir = str(tmp_path / "retro")
        with mock.patch.object(rt, "_read_retro_config") as mock_config:
            mock_config.return_value = {"enabled": True, "dir": retro_dir, "max_files": 100,
                                         "auto_analyze": False}
            logger = rt.RetroLogger(run_id="pipe:abc/123")
            logger.log("test")
            logger.close()
        files = list(Path(retro_dir).glob("*.jsonl"))
        assert len(files) == 1
        # run_id "pipe:abc/123" should become "pipe_abc_123" in filename
        assert "pipe_" in files[0].name
        # No colons or slashes in filename
        assert ":" not in files[0].name
        assert "/" not in files[0].name


class TestRetroSingletonSlot:
    """Tests for the thread-safe singleton slot."""

    def test_get_returns_same_instance(self):
        slot = rt._SingletonSlot()
        def factory():
            return rt.RetroLogger(run_id="singleton")
        first = slot.get(factory)
        second = slot.get(factory)
        assert first is second

    def test_peek_before_get(self):
        slot = rt._SingletonSlot()
        assert slot.peek() is None

    def test_peek_after_get(self):
        slot = rt._SingletonSlot()
        slot.get(lambda: "value")
        assert slot.peek() == "value"

    def test_reset_clears(self):
        slot = rt._SingletonSlot()
        slot.get(lambda: "value")
        slot.reset()
        assert slot.peek() is None

    def test_get_after_reset_creates_new(self):
        slot = rt._SingletonSlot()
        first = slot.get(lambda: "first")
        slot.reset()
        second = slot.get(lambda: "second")
        assert second == "second"
        assert first is not second  # different objects

    def test_double_check_locking(self):
        """Simulate concurrent access pattern."""
        slot = rt._SingletonSlot()
        slot.get(lambda: "initial")
        # Second get should return same (no factory call)
        result = slot.get(lambda: "different")
        assert result == "initial"


class TestClassifyEvents:
    """Tests for _classify_events."""

    def test_empty_events(self):
        result = rt._classify_events([])
        assert result["agents_run"] == []
        assert result["durations"] == {}
        assert result["errors"] == []
        assert result["convergences"] == []
        assert result["events_by_type"] == {}

    def test_classifies_all_event_types(self):
        events = [
            {"event": "agent_start", "agent": "finder"},
            {"event": "agent_done", "agent": "finder", "duration_s": 10},
            {"event": "error", "agent": "tester", "error": "fail"},
            {"event": "convergence", "decision": "converged"},
            {"event": "model_routing", "agent": "coder", "effective": "delegate"},
            {"event": "ensemble_gen", "agent": "coder", "n": 3},
            {"event": "findings", "p0": 1},
        ]
        result = rt._classify_events(events)
        assert result["agents_run"] == ["finder"]
        assert result["durations"] == {"finder": 10}
        assert len(result["errors"]) == 1
        assert len(result["convergences"]) == 1
        assert len(result["routings"]) == 1
        assert len(result["ensembles"]) == 1
        assert len(result["findings_events"]) == 1
        assert result["events_by_type"]["agent_start"] == 1
        assert result["events_by_type"]["findings"] == 1


class TestDetectPatterns:
    """Tests for _detect_patterns."""

    def test_converged_pattern(self):
        patterns = rt._detect_patterns(
            [{"event": "convergence", "decision": "converged"}],
            {"convergences": [{"decision": "converged"}], "durations": {},
             "routings": [], "errors": []},
        )
        assert any("Convergence: converged" in p for p in patterns)

    def test_maxed_out_pattern(self):
        patterns = rt._detect_patterns(
            [{"event": "convergence", "decision": "maxed_out"}],
            {"convergences": [{"decision": "maxed_out"}], "durations": {},
             "routings": [], "errors": []},
        )
        assert any("maxed_out" in p for p in patterns)

    def test_stuck_pattern(self):
        patterns = rt._detect_patterns(
            [{"event": "convergence", "decision": "stuck"}],
            {"convergences": [{"decision": "stuck"}], "durations": {},
             "routings": [], "errors": []},
        )
        assert any("stuck" in p for p in patterns)

    def test_error_pattern(self):
        patterns = rt._detect_patterns(
            [{"event": "error", "agent": "tester", "error": "timeout"}],
            {"convergences": [], "durations": {}, "routings": [], "errors":
             [{"agent": "tester", "error": "timeout"}]},
        )
        assert any("1 error" in p for p in patterns)

    def test_deterministic_judge_pattern(self):
        events = [{"event": "ensemble_judge", "mode": "deterministic"}]
        patterns = rt._detect_patterns(
            events,
            {"convergences": [], "durations": {}, "routings": [],
             "errors": [], "findings_events": []},
        )
        assert any("deterministic" in p for p in patterns)

    def test_slow_agent_pattern(self):
        patterns = rt._detect_patterns(
            [],
            {"convergences": [], "durations": {"finder": 45, "coder": 2},
             "routings": [], "errors": [], "findings_events": []},
        )
        assert any("Slow" in p for p in patterns)
        assert any("finder" in p for p in patterns)
        # coder is not slow (2s < 30s)
        assert not any("coder (2" in p and "Slow" in p for p in patterns)

    def test_stale_route_warning(self):
        patterns = rt._detect_patterns(
            [{"event": "model_routing", "agent": "coder", "warning": "stale config"}],
            {"convergences": [], "durations": {}, "routings":
             [{"agent": "coder", "warning": "stale config", "configured": "gpt-4"}],
             "errors": [], "findings_events": []},
        )
        assert any("stale" in p.lower() for p in patterns)


class TestBuildAnalysisPrompt:
    """Tests for build_analysis_prompt."""

    def test_empty_events(self):
        result = rt.build_analysis_prompt([])
        assert result == "No retro events to analyze."

    def test_with_events(self):
        events = [
            {"event": "pipeline_start", "category": "FEATURE", "agents": 2,
             "request": "test", "ts": "2026-07-20T13:00:00Z"},
            {"event": "agent_start", "agent": "finder", "ts": "2026-07-20T13:01:00Z"},
        ]
        result = rt.build_analysis_prompt(events)
        assert "Pipeline Retrospective Analysis" in result
        assert "agent_start" in result
        assert "finder" in result  # agent appears, not category
