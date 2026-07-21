"""
Integration tests for Pipeline Plugin v2.0 Kanban API.

Requires `hermes` CLI with Kanban support.
Skipped if the pipeline board doesn't exist.
Runs serially (one session) to avoid parent collisions.
"""

from __future__ import annotations

import importlib
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import kanban as kb


def _has_kanban():
    """Check if pipeline kanban.db exists (direct SQLite, not Hermes CLI)."""
    base = os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes"))
    return os.path.isfile(os.path.join(base, "kanban", "boards", "pipeline", "kanban.db"))


def _set_kanban_mode(mode: str):
    """Write kanban_mode to config.yaml and reload module."""
    cfg_path = os.path.join(os.path.dirname(kb.__file__), "config.yaml")
    with open(cfg_path) as f:
        orig = f.read()
    import re
    if re.search(r"kanban_mode:\s*\w+", orig):
        new = re.sub(r"kanban_mode:\s*\w+", f"kanban_mode: {mode}", orig)
    else:
        new = orig + f"\npipeline:\n  kanban_mode: {mode}\n"
    with open(cfg_path, "w") as f:
        f.write(new)
    kb._KANBAN_MODE = None
    importlib.reload(kb)


def _cleanup(state):
    """Close all tasks for a pipeline state."""
    if not state:
        return
    parent = state.get("kanban_parent_id")
    if not parent:
        return
    for tid in state.get("kanban_task_ids", {}).values():
        kb.complete(tid, result_summary="Int-test cleanup")
    kb.complete(parent, result_summary="Int-test cleanup")


@pytest.fixture(scope="session", autouse=True)
def clean_board():
    """Clean the board before and after the test session."""
    yield
    state = kb.scan_board()
    while state:
        _cleanup(state)
        time.sleep(0.3)
        state = kb.scan_board()


def _unique_state(pipeline=None):
    ts = str(time.time())
    return {
        "request": f"Int test {ts}",
        "category": "TEST",
        "pipeline": pipeline or ["finder", "coder", "tester"],
        "current_idx": 0,
        "completed": [],
        "context": {},
        "checkpoints": {},
        "status": "running",
    }


@pytest.fixture(scope="class", autouse=True)
def _ensure_legacy_for_integration():
    """Integration tests need legacy mode (direct SQLite kanban)."""
    _set_kanban_mode("legacy")
    yield
    _set_kanban_mode("native")


@pytest.mark.skipif(not _has_kanban(), reason="Kanban CLI or pipeline board not available")
class TestKanbanTreeIntegration:
    """Integration tests exercising create_task_tree against legacy SQLite kanban."""

    def test_create_task_tree_idempotent(self):
        """Calling create_task_tree twice with same state should not duplicate tasks."""
        state = _unique_state()
        first = kb.create_task_tree(dict(state))
        parent1 = first.get("kanban_parent_id")
        assert parent1 is not None
        assert len(first.get("kanban_task_ids", {})) == 3

        second = kb.create_task_tree(dict(state))
        assert second.get("kanban_parent_id") == parent1
        _cleanup(first)

    def test_create_task_tree_creates_children(self):
        """Each agent should have a child task on the board."""
        state = _unique_state()
        state = kb.create_task_tree(state)
        parent = state.get("kanban_parent_id")
        task_ids = state.get("kanban_task_ids", {})

        detail = kb.show_task(parent)
        child_ids = set(detail.get("children", []))
        created_ids = set(task_ids.values())
        assert created_ids.issubset(child_ids)
        _cleanup(state)

    def test_scan_board_roundtrip(self):
        """After create_task_tree + advance, scan_board should find the pipeline."""
        state = _unique_state()
        created = kb.create_task_tree(dict(state))
        parent_id = created.get("kanban_parent_id")

        kb.advance(created, "finder")
        time.sleep(0.3)

        restored = kb.scan_board()
        assert restored is not None, "scan_board should find active pipeline"
        assert restored.get("kanban_parent_id") == parent_id
        assert len(restored.get("pipeline", [])) == 3
        assert "finder" in restored.get("completed", [])

        _cleanup(created)

    def test_scan_board_after_complete(self):
        """After completing all tasks, scan_board should return None."""
        state = _unique_state()
        created = kb.create_task_tree(dict(state))
        _cleanup(created)
        time.sleep(0.3)

        restored = kb.scan_board()
        assert restored is None, "scan_board should return None after cleanup"
