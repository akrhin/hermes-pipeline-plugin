"""Tests for kanban_adapter.py — mock subprocess.run, test public API."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import kanban_adapter as ka


def _mock_run(stdout: str = "{}", returncode: int = 0, stderr: str = ""):
    """Helper: create a CompletedProcess that _kanban parses correctly."""
    return subprocess.CompletedProcess(
        args=[], returncode=returncode, stdout=stdout, stderr=stderr
    )


_CLI_PREFIX = ["hermes", "kanban", "--board", "pipeline"]


class TestCreateParent:
    """Tests for create_parent — returns task id or None."""

    def test_returns_id_from_result(self):
        """Happy path: subprocess stdout includes 'id'."""
        with mock.patch("kanban_adapter.subprocess.run") as mock_run:
            mock_run.return_value = _mock_run(stdout=json.dumps({"id": "task_42"}))
            result = ka.create_parent("Test title", body="body")
        assert result == "task_42"
        assert mock_run.call_count == 1

    def test_returns_task_id_key(self):
        """subprocess stdout includes 'task_id' (fallback key)."""
        with mock.patch("kanban_adapter.subprocess.run") as mock_run:
            mock_run.return_value = _mock_run(stdout=json.dumps({"task_id": "abc"}))
            result = ka.create_parent("Test title")
        assert result == "abc"

    def test_id_preferred_over_task_id(self):
        """id is checked before task_id."""
        with mock.patch("kanban_adapter.subprocess.run") as mock_run:
            mock_run.return_value = _mock_run(
                stdout=json.dumps({"id": "main_id", "task_id": "fallback_id"})
            )
            result = ka.create_parent("Test title")
        assert result == "main_id"

    def test_returns_none_on_empty_result(self):
        """Empty dict returns None (no id/task_id keys)."""
        with mock.patch("kanban_adapter.subprocess.run") as mock_run:
            mock_run.return_value = _mock_run(stdout="{}")
            result = ka.create_parent("Test title")
        assert result is None

    def test_returns_none_on_falsy_result(self):
        """Non-empty dict without id/task_id returns None."""
        with mock.patch("kanban_adapter.subprocess.run") as mock_run:
            mock_run.return_value = _mock_run(stdout=json.dumps({"foo": "bar"}))
            result = ka.create_parent("Test title")
        assert result is None

    def test_no_id_returns_none(self):
        """When result is truthy but has no id/task_id, return None (no fallback to key)."""
        with mock.patch("kanban_adapter.subprocess.run") as mock_run:
            mock_run.return_value = _mock_run(
                stdout=json.dumps({"some_other_field": "val"})
            )
            result = ka.create_parent("Test title", idempotency_key="ikey_123")
        assert result is None

    def test_idempotency_key_not_used_when_result_has_id(self):
        """idempotency_key is ignored if subprocess returned an id."""
        with mock.patch("kanban_adapter.subprocess.run") as mock_run:
            mock_run.return_value = _mock_run(stdout=json.dumps({"id": "real_id"}))
            result = ka.create_parent("Test title", idempotency_key="fallback")
        assert result == "real_id"

    def test_dispatches_with_correct_args(self):
        """Ensure subprocess.run is called with correct CLI args."""
        with mock.patch("kanban_adapter.subprocess.run") as mock_run:
            mock_run.return_value = _mock_run(stdout=json.dumps({"id": "t1"}))
            ka.create_parent("My Pipeline", body="desc", idempotency_key="ik")
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert cmd == [
            "hermes",
            "kanban",
            "--board",
            "pipeline",
            "create",
            "My Pipeline",
            "--body",
            "desc",
            "--priority",
            "2",
            "--assignee",
            "pipeline",
            "--idempotency-key",
            "ik",
        ]


class TestComplete:
    """Tests for complete — returns bool. No fallback logic in native adapter."""

    def test_returns_true_with_summary(self):
        """With result_summary provided, returns True on success."""
        with mock.patch("kanban_adapter.subprocess.run") as mock_run:
            mock_run.return_value = _mock_run(stdout='{"id": "task_1"}')
            result = ka.complete("task_42", result_summary="Done")
        assert result is True

    def test_returns_false_when_dispatch_fails(self):
        """Non-zero returncode → False."""
        with mock.patch("kanban_adapter.subprocess.run") as mock_run:
            mock_run.return_value = _mock_run(returncode=1, stderr="error")
            result = ka.complete("task_42")
        assert result is False

    def test_returns_true_without_summary(self):
        """Without result_summary, dispatches minimal args."""
        with mock.patch("kanban_adapter.subprocess.run") as mock_run:
            mock_run.return_value = _mock_run(stdout='{"id": "ok"}')
            result = ka.complete("task_42")
        assert result is True
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert cmd == _CLI_PREFIX + ["complete", "task_42"]

    def test_empty_summary_skips_summary_flag(self):
        """Empty string summary → no --summary flag, single call."""
        with mock.patch("kanban_adapter.subprocess.run") as mock_run:
            mock_run.return_value = _mock_run(stdout='{"id": "ok"}')
            result = ka.complete("task_42", result_summary="")
        assert result is True
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert cmd == _CLI_PREFIX + ["complete", "task_42"]

    def test_empty_task_id_returns_false(self):
        """Empty task_id returns False without calling subprocess."""
        with mock.patch("kanban_adapter.subprocess.run") as mock_run:
            result = ka.complete("")
        assert result is False
        mock_run.assert_not_called()


class TestBlock:
    """Tests for block — returns bool."""

    def test_returns_true_on_success(self):
        """Happy path: subprocess returns success."""
        with mock.patch("kanban_adapter.subprocess.run") as mock_run:
            mock_run.return_value = _mock_run(stdout='{"id": "task_1"}')
            result = ka.block("task_42", reason="needs_input")
        assert result is True

    def test_returns_false_on_error(self):
        """Non-zero returncode returns False."""
        with mock.patch("kanban_adapter.subprocess.run") as mock_run:
            mock_run.return_value = _mock_run(returncode=1, stderr="error")
            result = ka.block("task_42")
        assert result is False

    def test_dependency_reason_uses_todo_status(self):
        """reason='dependency' → update --status todo."""
        with mock.patch("kanban_adapter.subprocess.run") as mock_run:
            mock_run.return_value = _mock_run(stdout='{"id": "ok"}')
            ka.block("task_42", reason="dependency")
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert cmd == _CLI_PREFIX + ["update", "task_42", "--status", "todo"]

    def test_needs_input_reason_uses_block(self):
        """reason='needs_input' → block --reason."""
        with mock.patch("kanban_adapter.subprocess.run") as mock_run:
            mock_run.return_value = _mock_run(stdout='{"id": "ok"}')
            ka.block("task_42", reason="needs_input")
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert cmd == _CLI_PREFIX + ["block", "task_42", "--reason", "needs_input"]

    def test_capability_reason_uses_block(self):
        """reason='capability' → block --reason."""
        with mock.patch("kanban_adapter.subprocess.run") as mock_run:
            mock_run.return_value = _mock_run(stdout='{"id": "ok"}')
            ka.block("task_42", reason="capability")
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert cmd == _CLI_PREFIX + ["block", "task_42", "--reason", "capability"]

    def test_transient_reason_uses_block(self):
        """reason='transient' → block --reason."""
        with mock.patch("kanban_adapter.subprocess.run") as mock_run:
            mock_run.return_value = _mock_run(stdout='{"id": "ok"}')
            ka.block("task_42", reason="transient")
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert cmd == _CLI_PREFIX + ["block", "task_42", "--reason", "transient"]

    def test_unknown_reason_defaults_to_block(self):
        """Unknown reason → block --reason."""
        with mock.patch("kanban_adapter.subprocess.run") as mock_run:
            mock_run.return_value = _mock_run(stdout='{"id": "ok"}')
            ka.block("task_42", reason="whatever")
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert cmd == _CLI_PREFIX + ["block", "task_42", "--reason", "whatever"]

    def test_empty_task_id_returns_false(self):
        """Empty task_id returns False without calling subprocess."""
        with mock.patch("kanban_adapter.subprocess.run") as mock_run:
            result = ka.block("")
        assert result is False
        mock_run.assert_not_called()


class TestBlockTask:
    """Tests for block_task alias — matches block behaviour."""

    def test_alias(self):
        """block_task delegates to block."""
        with mock.patch.object(ka.subprocess, "run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="ok", stderr=""
            )
            assert ka.block_task("t_abc") == ka.block("t_abc")

    def test_block_task_returns_true(self):
        with mock.patch("kanban_adapter.subprocess.run") as mock_run:
            mock_run.return_value = _mock_run(stdout='{"id": "ok"}')
            result = ka.block_task("t1")
        assert result is True


class TestListTasks:
    """Tests for list_tasks — returns list."""

    def test_returns_empty_list_on_cli_error(self):
        """CLI error (returncode=1) → []."""
        with mock.patch("kanban_adapter.subprocess.run") as mock_run:
            mock_run.return_value = _mock_run(returncode=1, stderr="error")
            result = ka.list_tasks()
        assert result == []

    def test_returns_list_from_json_array(self):
        """stdout JSON array → list via _kanban tasks-wrapping."""
        tasks = [{"id": "1", "status": "done"}, {"id": "2", "status": "ready"}]
        with mock.patch("kanban_adapter.subprocess.run") as mock_run:
            mock_run.return_value = _mock_run(stdout=json.dumps(tasks))
            result = ka.list_tasks()
        assert result == tasks

    def test_returns_list_from_tasks_key(self):
        """stdout JSON object with 'tasks' key."""
        tasks = [{"id": "1", "status": "done"}]
        with mock.patch("kanban_adapter.subprocess.run") as mock_run:
            mock_run.return_value = _mock_run(stdout=json.dumps({"tasks": tasks}))
            result = ka.list_tasks()
        assert result == tasks

    def test_data_key_returns_empty_list(self):
        """Dict with 'data' key (not 'tasks') → [] (adapter only handles 'tasks')."""
        with mock.patch("kanban_adapter.subprocess.run") as mock_run:
            mock_run.return_value = _mock_run(
                stdout=json.dumps({"data": [{"id": "1"}]})
            )
            result = ka.list_tasks()
        assert result == []

    def test_wraps_single_item_dict_in_list(self):
        """Single non-list dict wraps in list if it has 'id'."""
        item = {"id": "1"}
        with mock.patch("kanban_adapter.subprocess.run") as mock_run:
            mock_run.return_value = _mock_run(stdout=json.dumps(item))
            result = ka.list_tasks()
        assert result == [item]

    def test_empty_dict_returns_empty_list(self):
        """Empty dict → [] (no id key → fallthrough to [])."""
        with mock.patch("kanban_adapter.subprocess.run") as mock_run:
            mock_run.return_value = _mock_run(stdout="{}")
            result = ka.list_tasks()
        assert result == []

    def test_filters_by_status(self):
        """status_filter='done' passes --status done to CLI."""
        done_tasks = [{"id": "1", "status": "done"}, {"id": "3", "status": "done"}]
        with mock.patch("kanban_adapter.subprocess.run") as mock_run:
            mock_run.return_value = _mock_run(stdout=json.dumps(done_tasks))
            result = ka.list_tasks(status_filter="done")
        assert result == done_tasks
        cmd = mock_run.call_args[0][0]
        assert "--status" in cmd
        assert cmd[cmd.index("--status") + 1] == "done"

    def test_status_filter_no_matches(self):
        """Filter for status with no matches returns []."""
        with mock.patch("kanban_adapter.subprocess.run") as mock_run:
            mock_run.return_value = _mock_run(stdout="[]")
            result = ka.list_tasks(status_filter="nonexistent")
        assert result == []

    def test_dispatches_with_board_name(self):
        """list_tasks passes --board pipeline to CLI."""
        with mock.patch("kanban_adapter.subprocess.run") as mock_run:
            mock_run.return_value = _mock_run(stdout="[]")
            ka.list_tasks()
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert cmd == _CLI_PREFIX + ["list"]
