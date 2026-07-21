"""Unit tests for handlers/__init__.py — handler functions, metrics, dispatch."""

from __future__ import annotations

import json
import os
import sys
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Force deterministic tests — игнорировать локальный config.yaml
import models as models_module

mock.patch.object(models_module, "_read_config_section", return_value=None).start()

import __init__ as plugin  # noqa: E402
from handlers import (  # noqa: E402
    _on_pre_tool_call,
    get_pipeline_metrics,
    handle_pipeline_command,
)


class TestMetricsHook:
    """Tests for the pre_tool_call metrics hook."""

    def setup_method(self):
        # Reset counters between tests
        from handlers import _PIPELINE_TOOL_COUNTERS
        _PIPELINE_TOOL_COUNTERS.clear()

    def test_counts_pipeline_tools(self):
        _on_pre_tool_call("pipeline_classify", {}, "task_1")
        _on_pre_tool_call("pipeline_classify", {}, "task_2")
        _on_pre_tool_call("pipeline_convergence", {}, "task_3")
        metrics = get_pipeline_metrics()
        assert metrics.get("pipeline_classify") == 2
        assert metrics.get("pipeline_convergence") == 1

    def test_counts_agent_tools(self):
        _on_pre_tool_call("agent_model", {}, "task_1")
        _on_pre_tool_call("agent_prompt", {}, "task_2")
        metrics = get_pipeline_metrics()
        assert metrics.get("agent_model") == 1
        assert metrics.get("agent_prompt") == 1

    def test_ignores_non_pipeline_tools(self):
        _on_pre_tool_call("web_search", {}, "task_1")
        _on_pre_tool_call("read_file", {}, "task_2")
        metrics = get_pipeline_metrics()
        assert len(metrics) == 0

    def test_metrics_isolated_instance(self):
        """get_pipeline_metrics returns a copy, not the internal dict."""
        _on_pre_tool_call("pipeline_classify", {}, "t1")
        metrics = get_pipeline_metrics()
        metrics["fake"] = "value"
        # Internal counters should not have 'fake'
        from handlers import _PIPELINE_TOOL_COUNTERS
        assert "fake" not in _PIPELINE_TOOL_COUNTERS


class TestHandlePipelineCommand:
    """Tests for the /pipeline slash command."""

    def test_status_default(self):
        with mock.patch("handlers.kb.scan_board") as mock_scan:
            mock_scan.return_value = None
            result = handle_pipeline_command("")
        assert "No active pipeline" in result

    def test_status_show(self):
        with mock.patch("handlers.kb.scan_board") as mock_scan:
            mock_scan.return_value = None
            result = handle_pipeline_command("show")
        assert "No active pipeline" in result

    def test_clear_without_active(self):
        with mock.patch("handlers.kb.scan_board") as mock_scan:
            mock_scan.return_value = None
            result = handle_pipeline_command("clear")
        assert "No active pipeline" in result

    def test_clear_with_active(self):
        with mock.patch("handlers.kb.scan_board") as mock_scan, \
             mock.patch("handlers.kb.on_clear") as mock_clear, \
             mock.patch("handlers.rt.reset_retro") as mock_reset:
            mock_scan.return_value = {"kanban_parent_id": "pipe:abc", "pipeline": ["finder"]}
            result = handle_pipeline_command("clear")
        assert "cleared" in result.lower()
        mock_clear.assert_called_once()
        mock_reset.assert_called_once()

    def test_status_with_active_pipeline(self):
        state = {
            "request": "test",
            "category": "FEATURE",
            "pipeline": ["finder", "coder", "tester"],
            "completed": ["finder"],
            "current_idx": 1,
            "round": 0,
        }
        with mock.patch("handlers.kb.scan_board") as mock_scan:
            mock_scan.return_value = state
            result = handle_pipeline_command("status")
        assert "test" in result
        assert "Feature" in result or "FEATURE" in result
        assert "@coder" in result or "@finder" in result

    def test_unknown_command(self):
        with mock.patch("handlers.kb.scan_board"):
            result = handle_pipeline_command("unknown")
        assert "Usage" in result


class TestHandleConvergenceEdgeCases:
    """Additional edge cases for handle_convergence handler."""

    def test_no_findings_shortcircuits(self):
        """When findings is None and state has no findings → unknown."""
        result = json.loads(plugin.handle_convergence({"state": {"round": 0}}))
        assert result["decision"] == "unknown"

    def test_empty_findings_shortcircuits(self):
        """Empty findings list is treated as 'no findings' by convergence."""
        result = json.loads(plugin.handle_convergence({
            "state": {"round": 0},
            "findings": [],
        }))
        # Empty findings → normalize to None in evaluate_convergence → converged
        assert result["decision"] in ("unknown", "converged")

    def test_with_findings(self):
        state = {"round": 0, "pipeline": ["finder", "coder"]}
        findings = [{"severity": "P0", "file": "x.py", "category": "sec", "description": "bug"}]
        with mock.patch("handlers.kb.on_convergence") as mock_oc, \
             mock.patch("handlers.rt.get_retro") as mock_retro:
            mock_retro.return_value = mock.MagicMock()
            result = json.loads(plugin.handle_convergence({
                "state": state, "findings": findings,
            }))
        assert result["decision"] in ("continue",)
        mock_oc.assert_called_once()


class TestHandleClassifyEdgeCases:
    """Additional edge cases for handle_classify."""

    def test_empty_request(self):
        with mock.patch("handlers.rt.get_retro") as mock_retro:
            mock_retro.return_value = mock.MagicMock()
            result = json.loads(plugin.handle_classify({"request": ""}))
        assert "primary" in result
        assert result["primary"] == "FEATURE"

    def test_missing_request_key(self):
        result = json.loads(plugin.handle_classify({}))
        assert "error" in result


class TestHandleSaveEdgeCases:
    """Edge cases for handle_save."""

    def test_missing_state(self):
        result = json.loads(plugin.handle_save({}))
        assert "error" in result

    def test_exception_handling(self):
        """When state has existing kanban_parent_id, save returns without error."""
        result = json.loads(plugin.handle_save({"state": {"kanban_parent_id": "existing"}}))
        # Existing parent_id means "already created" — returns ok
        assert "error" not in result, f"Unexpected error: {result}"


class TestHandleClear:
    """Tests for handle_clear."""

    def test_no_active_pipeline(self):
        with mock.patch("handlers.kb.scan_board") as mock_scan:
            mock_scan.return_value = None
            result = json.loads(plugin.handle_clear({}))
        assert result["status"] == "ok"

    def test_with_active_pipeline(self):
        with mock.patch("handlers.kb.scan_board") as mock_scan, \
             mock.patch("handlers.kb.on_clear") as mock_clear, \
             mock.patch("handlers.rt.reset_retro") as mock_reset, \
             mock.patch("handlers.rt.get_retro") as mock_retro:
            mock_scan.return_value = {"kanban_parent_id": "pipe:abc"}
            mock_retro.return_value = mock.MagicMock()
            result = json.loads(plugin.handle_clear({}))
        assert result["status"] == "ok"
        mock_clear.assert_called_once()
        mock_reset.assert_called_once()


class TestHandleLoad:
    """Tests for handle_load."""

    def test_no_active(self):
        with mock.patch("handlers.kb.scan_board") as mock_scan, \
             mock.patch("handlers.rt.get_retro") as mock_retro:
            mock_scan.return_value = None
            mock_retro.return_value = mock.MagicMock()
            result = json.loads(plugin.handle_load({}))
        assert result is None

    def test_with_active(self):
        state = {"request": "test", "pipeline": ["finder"], "kanban_parent_id": "pipe:abc"}
        with mock.patch("handlers.kb.scan_board") as mock_scan, \
             mock.patch("handlers.rt.get_retro") as mock_retro:
            mock_scan.return_value = state
            mock_retro.return_value = mock.MagicMock()
            result = json.loads(plugin.handle_load({}))
        assert result["request"] == "test"


class TestHandleResume:
    """Tests for handle_resume."""

    def test_no_active(self):
        with mock.patch("handlers.kb.scan_board") as mock_scan:
            mock_scan.return_value = None
            result = json.loads(plugin.handle_resume({}))
        assert result is None

    def test_with_active(self):
        state = {"request": "resume test", "pipeline": ["finder", "coder"]}
        with mock.patch("handlers.kb.scan_board") as mock_scan, \
             mock.patch("handlers.rt.get_retro") as mock_retro:
            mock_scan.return_value = state
            mock_retro.return_value = mock.MagicMock()
            result = json.loads(plugin.handle_resume({}))
        assert result["request"] == "resume test"


class TestHandleAdvanceEdgeCases:
    """Edge cases for handle_advance."""

    def test_missing_agent_key(self):
        result = json.loads(plugin.handle_advance({"state": {"pipeline": ["finder"]}}))
        assert "error" in result

    def test_missing_state_key(self):
        result = json.loads(plugin.handle_advance({}))
        assert "error" in result

    def test_successful_advance(self):
        with mock.patch("handlers.kb.advance") as mock_adv, \
             mock.patch("handlers.rt.get_retro") as mock_retro:
            mock_adv.return_value = {"current_idx": 1, "completed": ["finder"]}
            mock_retro.return_value = mock.MagicMock()
            result = json.loads(plugin.handle_advance({
                "state": {"pipeline": ["finder", "coder"]},
                "completed_agent": "finder",
            }))
        assert result["current_idx"] == 1
        assert "finder" in result["completed"]


class TestEnsembleEnabled:
    """Tests for _ensemble_enabled check_fn."""

    def test_enabled_by_default(self):
        with mock.patch("ensemble.read_ensemble_config") as mock_read:
            mock_read.return_value = {"enabled": True}
            from __init__ import _ensemble_enabled
            assert _ensemble_enabled() is True

    def test_disabled_explicitly(self):
        with mock.patch("ensemble.read_ensemble_config") as mock_read:
            mock_read.return_value = {"enabled": False}
            from __init__ import _ensemble_enabled
            assert _ensemble_enabled() is False

    def test_fail_open_on_error(self):
        with mock.patch("ensemble.read_ensemble_config") as mock_read:
            mock_read.side_effect = Exception("Config error")
            from __init__ import _ensemble_enabled
            assert _ensemble_enabled() is True  # fail open
