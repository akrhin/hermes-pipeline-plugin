"""Tests for kanban_adapter.py — mock dispatch_tool, test public API."""

from __future__ import annotations

import os
import sys
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import kanban_adapter as ka


class TestCreateParent:
    """Tests for create_parent — returns task id or None."""

    def test_returns_id_from_result(self):
        """Happy path: dispatch returns {'id': 'task_42'}."""
        with mock.patch("kanban_adapter._board_dispatch") as mock_dispatch:
            mock_dispatch.return_value = {"id": "task_42"}
            result = ka.create_parent("Test title", body="body")
        assert result == "task_42"
        # Verify dispatched kanban_create
        assert mock_dispatch.call_args is not None
        args, kwargs = mock_dispatch.call_args
        assert args[0] == "kanban_create"

    def test_returns_task_id_key(self):
        """dispatch returns {'task_id': 'abc'}."""
        with mock.patch("kanban_adapter._board_dispatch") as mock_dispatch:
            mock_dispatch.return_value = {"task_id": "abc"}
            result = ka.create_parent("Test title")
        assert result == "abc"

    def test_id_preferred_over_task_id(self):
        """id is checked before task_id."""
        with mock.patch("kanban_adapter._board_dispatch") as mock_dispatch:
            mock_dispatch.return_value = {"id": "main_id", "task_id": "fallback_id"}
            result = ka.create_parent("Test title")
        assert result == "main_id"

    def test_returns_none_on_empty_result(self):
        """Empty dict returns None."""
        with mock.patch("kanban_adapter._board_dispatch") as mock_dispatch:
            mock_dispatch.return_value = {}
            result = ka.create_parent("Test title")
        assert result is None

    def test_returns_none_on_falsy_result(self):
        """None result returns None."""
        with mock.patch("kanban_adapter._board_dispatch") as mock_dispatch:
            mock_dispatch.return_value = {}
            result = ka.create_parent("Test title")
        assert result is None

    def test_fallback_to_idempotency_key(self):
        """When result is truthy but has no id, return idempotency_key."""
        with mock.patch("kanban_adapter._board_dispatch") as mock_dispatch:
            # Must be truthy so `if not result:` doesn't short-circuit
            mock_dispatch.return_value = {"some_other_field": "val"}
            result = ka.create_parent("Test title", idempotency_key="ikey_123")
        assert result == "ikey_123"

    def test_idempotency_key_not_used_when_result_has_id(self):
        """idempotency_key is ignored if dispatch returned an id."""
        with mock.patch("kanban_adapter._board_dispatch") as mock_dispatch:
            mock_dispatch.return_value = {"id": "real_id"}
            result = ka.create_parent("Test title", idempotency_key="fallback")
        assert result == "real_id"

    def test_dispatches_with_correct_args(self):
        """Ensure kanban_create is called with title, body, status, priority, assignee."""
        with mock.patch("kanban_adapter._board_dispatch") as mock_dispatch:
            mock_dispatch.return_value = {"id": "t1"}
            ka.create_parent("My Pipeline", body="desc", idempotency_key="ik")
        mock_dispatch.assert_called_once_with(
            "kanban_create",
            title="My Pipeline",
            body="desc",
            status="ready",
            priority=1,
            assignee="pipeline",
        )


class TestComplete:
    """Tests for complete — returns bool."""

    def test_returns_true_with_summary(self):
        """With result_summary provided, returns True on success."""
        with mock.patch("kanban_adapter._board_dispatch") as mock_dispatch:
            mock_dispatch.return_value = {"id": "task_1"}
            result = ka.complete("task_42", result_summary="Done")
        assert result is True

    def test_returns_false_when_dispatch_fails(self):
        """dispatch returning falsy → False."""
        with mock.patch("kanban_adapter._board_dispatch") as mock_dispatch:
            mock_dispatch.return_value = {}
            result = ka.complete("task_42")
        assert result is False

    def test_fallback_when_summary_dispatch_fails(self):
        """First call with summary fails, fallback without summary succeeds."""
        dispatch_results = iter([{}, {"id": "ok"}])
        with mock.patch("kanban_adapter._board_dispatch") as mock_dispatch:
            mock_dispatch.side_effect = lambda *a, **kw: next(dispatch_results)
            result = ka.complete("task_42", result_summary="Done")
        assert result is True
        assert mock_dispatch.call_count == 2

    def test_fallback_also_fails(self):
        """Both summary and fallback fail → False."""
        dispatch_results = iter([{}, {}])
        with mock.patch("kanban_adapter._board_dispatch") as mock_dispatch:
            mock_dispatch.side_effect = lambda *a, **kw: next(dispatch_results)
            result = ka.complete("task_42", result_summary="Done")
        assert result is False
        assert mock_dispatch.call_count == 2

    def test_returns_true_without_summary(self):
        """Without result_summary, dispatches minimal args."""
        with mock.patch("kanban_adapter._board_dispatch") as mock_dispatch:
            mock_dispatch.return_value = {"id": "ok"}
            result = ka.complete("task_42")
        assert result is True
        # Should call kanban_complete with just task_id
        assert mock_dispatch.call_count == 1
        args, kwargs = mock_dispatch.call_args
        assert args[0] == "kanban_complete"
        assert kwargs.get("task_id") == "task_42"

    def test_empty_summary_skips_first_branch(self):
        """Empty string summary skips the summary call, goes straight to fallback."""
        with mock.patch("kanban_adapter._board_dispatch") as mock_dispatch:
            mock_dispatch.return_value = {"id": "ok"}
            result = ka.complete("task_42", result_summary="")
        assert result is True
        # Only the fallback call (without summary)
        assert mock_dispatch.call_count == 1
        assert "summary" not in mock_dispatch.call_args[1]


class TestBlock:
    """Tests for block — returns bool."""

    def test_returns_true_on_success(self):
        """Happy path: dispatch returns truthy."""
        with mock.patch("kanban_adapter._board_dispatch") as mock_dispatch:
            mock_dispatch.return_value = {"id": "task_1"}
            result = ka.block("task_42", reason="needs_input")
        assert result is True

    def test_returns_false_on_empty_result(self):
        """Empty dict returns False."""
        with mock.patch("kanban_adapter._board_dispatch") as mock_dispatch:
            mock_dispatch.return_value = {}
            result = ka.block("task_42")
        assert result is False

    def test_dependency_reason_uses_todo_status(self):
        """reason='dependency' → status='todo'."""
        with mock.patch("kanban_adapter._board_dispatch") as mock_dispatch:
            mock_dispatch.return_value = {"id": "ok"}
            ka.block("task_42", reason="dependency")
        mock_dispatch.assert_called_once_with(
            "kanban_block", task_id="task_42", status="todo", reason="dependency"
        )

    def test_needs_input_reason_uses_blocked_status(self):
        """reason='needs_input' → status='blocked'."""
        with mock.patch("kanban_adapter._board_dispatch") as mock_dispatch:
            mock_dispatch.return_value = {"id": "ok"}
            ka.block("task_42", reason="needs_input")
        mock_dispatch.assert_called_once_with(
            "kanban_block", task_id="task_42", status="blocked", reason="needs_input"
        )

    def test_capability_reason_uses_blocked_status(self):
        """reason='capability' → status='blocked'."""
        with mock.patch("kanban_adapter._board_dispatch") as mock_dispatch:
            mock_dispatch.return_value = {"id": "ok"}
            ka.block("task_42", reason="capability")
        mock_dispatch.assert_called_once_with(
            "kanban_block", task_id="task_42", status="blocked", reason="capability"
        )

    def test_transient_reason_uses_blocked_status(self):
        """reason='transient' → status='blocked'."""
        with mock.patch("kanban_adapter._board_dispatch") as mock_dispatch:
            mock_dispatch.return_value = {"id": "ok"}
            ka.block("task_42", reason="transient")
        mock_dispatch.assert_called_once_with(
            "kanban_block", task_id="task_42", status="blocked", reason="transient"
        )

    def test_unknown_reason_defaults_to_blocked(self):
        """Unknown reason → status='blocked'."""
        with mock.patch("kanban_adapter._board_dispatch") as mock_dispatch:
            mock_dispatch.return_value = {"id": "ok"}
            ka.block("task_42", reason="whatever")
        mock_dispatch.assert_called_once_with(
            "kanban_block", task_id="task_42", status="blocked", reason="whatever"
        )


class TestBlockTask:
    """Tests for block_task alias — matches block behaviour."""

    def test_block_task_is_block(self):
        assert ka.block_task is ka.block

    def test_block_task_returns_true(self):
        with mock.patch("kanban_adapter._board_dispatch") as mock_dispatch:
            mock_dispatch.return_value = {"id": "ok"}
            result = ka.block_task("t1")
        assert result is True


class TestListTasks:
    """Tests for list_tasks — returns list."""

    def test_returns_empty_list_when_dispatch_returns_none(self):
        """None result → []."""
        with mock.patch("kanban_adapter._board_dispatch_raw") as mock_dispatch_raw:
            mock_dispatch_raw.return_value = None
            result = ka.list_tasks()
        assert result == []

    def test_returns_list_directly(self):
        """When dispatch returns a list, use it directly."""
        tasks = [{"id": "1", "status": "done"}, {"id": "2", "status": "ready"}]
        with mock.patch("kanban_adapter._board_dispatch_raw") as mock_dispatch_raw:
            mock_dispatch_raw.return_value = tasks
            result = ka.list_tasks()
        assert result == tasks

    def test_extracts_tasks_from_dict(self):
        """Dict with 'tasks' key extracts that value."""
        tasks = [{"id": "1", "status": "done"}]
        with mock.patch("kanban_adapter._board_dispatch_raw") as mock_dispatch_raw:
            mock_dispatch_raw.return_value = {"tasks": tasks}
            result = ka.list_tasks()
        assert result == tasks

    def test_extracts_data_from_dict(self):
        """Dict with 'data' key extracts that value."""
        tasks = [{"id": "1"}]
        with mock.patch("kanban_adapter._board_dispatch_raw") as mock_dispatch_raw:
            mock_dispatch_raw.return_value = {"data": tasks}
            result = ka.list_tasks()
        assert result == tasks

    def test_wraps_single_item_dict_in_list(self):
        """Single non-list dict wraps in list."""
        item = {"id": "1"}
        with mock.patch("kanban_adapter._board_dispatch_raw") as mock_dispatch_raw:
            mock_dispatch_raw.return_value = item
            result = ka.list_tasks()
        assert result == [item]

    def test_empty_dict_wraps_in_list(self):
        """Empty dict wraps as [{}] (matching adapter behaviour)."""
        with mock.patch("kanban_adapter._board_dispatch_raw") as mock_dispatch_raw:
            mock_dispatch_raw.return_value = {}
            result = ka.list_tasks()
        assert result == [{}]

    def test_filters_by_status(self):
        """status_filter='done' returns only done tasks."""
        tasks = [
            {"id": "1", "status": "done"},
            {"id": "2", "status": "ready"},
            {"id": "3", "status": "done"},
        ]
        with mock.patch("kanban_adapter._board_dispatch_raw") as mock_dispatch_raw:
            mock_dispatch_raw.return_value = tasks
            result = ka.list_tasks(status_filter="done")
        assert result == [{"id": "1", "status": "done"}, {"id": "3", "status": "done"}]

    def test_status_filter_no_matches(self):
        """Filter for status with no matches returns []."""
        tasks = [{"id": "1", "status": "done"}]
        with mock.patch("kanban_adapter._board_dispatch_raw") as mock_dispatch_raw:
            mock_dispatch_raw.return_value = tasks
            result = ka.list_tasks(status_filter="nonexistent")
        assert result == []

    def test_dispatches_with_board_name(self):
        """Does not crash when called with no filter."""
        with mock.patch("kanban_adapter._board_dispatch_raw") as mock_dispatch_raw:
            mock_dispatch_raw.return_value = []
            ka.list_tasks()
        assert mock_dispatch_raw.call_count == 1
        args, kwargs = mock_dispatch_raw.call_args
        assert args[0] == "kanban_list"
        assert kwargs.get("board") == "pipeline"
