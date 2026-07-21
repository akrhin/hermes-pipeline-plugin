"""Tests for kanban.py router — mode selection, engine loading, _db_path, _get_connection.

Verifies that:
  - Default config.yaml (native) loads kanban_adapter engine functions
  - Switching to 'legacy' via config.yaml loads kanban_legacy engine functions
  - _db_path() points to the correct DB path in both modes
  - _get_connection() returns sqlite3.Connection in legacy mode, None in native mode
  - The full public API surface is available from both engines
  - Config file errors gracefully fall back to 'native'
"""

from __future__ import annotations

import importlib
import logging
import os
import re
import sqlite3
import sys
from contextlib import contextmanager
from unittest import mock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

logging.disable(logging.CRITICAL)  # suppress module-level log messages during reloads


# ── Helpers ────────────────────────────────────────────────────────────────────


# All functions the router is expected to re-export from either engine
PUBLIC_API = {
    "advance",
    "block",
    "block_task",
    "comment",
    "complete",
    "create_child",
    "create_ensemble_subtasks",
    "create_parent",
    "create_task_tree",
    "list_tasks",
    "on_clear",
    "on_convergence",
    "promote",
    "reopen",
    "scan_board",
    "show_task",
    "_claim_and_assign",
    "_cleanup_stale_pipelines",
    "_close_connection",
    "_db_path",
    "_get_connection",
}

LEGACY_ONLY_API = {
    "_find_active_parent",
    "_sqlite_select",
    "_sqlite_update",
    "_update_parent_body",
    "_update_parent_status",
}


def _plugin_dir() -> str:
    """Return the plugin root directory (where kanban.py and config.yaml live)."""
    import kanban  # noqa: F401
    return os.path.dirname(os.path.abspath(kanban.__file__))


def _read_config() -> str:
    """Read the current config.yaml content."""
    cfg_path = os.path.join(_plugin_dir(), "config.yaml")
    with open(cfg_path) as f:
        return f.read()


def _write_config(content: str) -> None:
    """Write content to config.yaml."""
    cfg_path = os.path.join(_plugin_dir(), "config.yaml")
    with open(cfg_path, "w") as f:
        f.write(content)


@contextmanager
def _kanban_mode(mode: str):
    """Temporarily switch config.yaml kanban_mode and reload kanban module.

    Restores original config on exit.
    """
    import kanban

    orig = _read_config()

    if re.search(r"kanban_mode:\s*\w+", orig):
        new_content = re.sub(r"kanban_mode:\s*\w+", f"kanban_mode: {mode}", orig)
    else:
        new_content = orig + f"\npipeline:\n  kanban_mode: {mode}\n"

    _write_config(new_content)
    kanban._KANBAN_MODE = None
    importlib.reload(kanban)

    try:
        yield kanban
    finally:
        _write_config(orig)
        kanban._KANBAN_MODE = None
        importlib.reload(kanban)


# ── Mode switching ──────────────────────────────────────────────────────────────


class TestKanbanMode:
    """Tests that kanban.py selects the correct engine based on kanban_mode."""

    def test_native_is_default(self):
        """Default config.yaml has native → kanban_adapter loaded."""
        import kanban as kb

        from kanban_adapter import _db_path as _adapter_db_path
        from kanban_adapter import _get_connection as _adapter_get_connection

        assert kb._db_path is _adapter_db_path, "_db_path should be kanban_adapter's"
        assert kb._get_connection is _adapter_get_connection, "_get_connection should be kanban_adapter's"
        assert kb._debug_mode() == "native"
        assert kb._is_native_mode() is True

    def test_legacy_mode_via_config(self):
        """Switching config.yaml to 'legacy' and reloading → kanban_legacy loaded."""
        with _kanban_mode("legacy") as kb:
            from kanban_legacy import _db_path as _legacy_db_path
            from kanban_legacy import _get_connection as _legacy_get_connection

            assert kb._db_path is _legacy_db_path
            assert kb._get_connection is _legacy_get_connection
            assert kb._debug_mode() == "legacy"
            assert kb._is_native_mode() is False

    def test_native_after_return_from_legacy(self):
        """After exiting the legacy context, native engine is restored."""
        with _kanban_mode("legacy") as kb:
            assert kb._debug_mode() == "legacy"

        import kanban as kb
        assert kb._debug_mode() == "native"
        assert kb._is_native_mode() is True

    def test_round_trip_legacy_native_legacy(self):
        """Multiple mode switches work correctly."""
        import kanban as kb
        native_db_path = kb._db_path
        assert kb._debug_mode() == "native"

        with _kanban_mode("legacy") as kb_l:
            assert kb_l._debug_mode() == "legacy"
            assert kb_l._db_path is not native_db_path

        assert kb._debug_mode() == "native"

        with _kanban_mode("legacy") as kb_l2:
            assert kb_l2._debug_mode() == "legacy"
            assert kb_l2._db_path is not native_db_path


# ── _db_path ────────────────────────────────────────────────────────────────────


class TestDbPath:
    """Tests for _db_path() behavior in both modes."""

    def test_db_path_native(self):
        """_db_path() returns the correct path in native mode."""
        import kanban as kb

        path = kb._db_path()
        assert path.endswith("kanban.db")
        assert "kanban" in path
        assert "pipeline" in path

        with pytest.MonkeyPatch.context() as mp:
            mp.setenv("HERMES_HOME", "/tmp/test_native")
            path2 = kb._db_path()
            assert path2.startswith("/tmp/test_native/")
            assert path2.endswith("kanban/boards/pipeline/kanban.db")

    def test_db_path_legacy(self):
        """_db_path() returns the same logical path in legacy mode."""
        with _kanban_mode("legacy") as kb:
            path = kb._db_path()
            assert path.endswith("kanban.db")
            assert "kanban" in path
            assert "pipeline" in path

            with pytest.MonkeyPatch.context() as mp:
                mp.setenv("HERMES_HOME", "/tmp/test_hermes_home_legacy")
                path2 = kb._db_path()
                assert path2.startswith("/tmp/test_hermes_home_legacy/")
                assert path2.endswith("kanban/boards/pipeline/kanban.db")

    def test_db_path_identical_between_modes(self):
        """Both modes compute the same DB path for the same HERMES_HOME."""
        import kanban as kb

        with pytest.MonkeyPatch.context() as mp:
            mp.setenv("HERMES_HOME", "/tmp/test_common")
            native_path = kb._db_path()

            with _kanban_mode("legacy") as kb_l:
                legacy_path = kb_l._db_path()

            assert legacy_path == native_path


# ── _get_connection ──────────────────────────────────────────────────────────────


class TestGetConnection:
    """Tests for _get_connection() behavior in both modes."""

    def test_get_connection_native(self):
        """_get_connection() returns None in native mode (no direct SQLite)."""
        import kanban as kb

        conn = kb._get_connection()
        assert conn is None, "Native mode should return None from _get_connection()"

    def test_get_connection_legacy(self):
        """_get_connection() returns a real sqlite3.Connection in legacy mode."""
        with _kanban_mode("legacy") as kb:
            conn = kb._get_connection()
            assert isinstance(conn, sqlite3.Connection)
            assert conn is not None

            cur = conn.execute("SELECT 1 AS val")
            row = cur.fetchone()
            assert row is not None
            assert row["val"] == 1

    def test_get_connection_legacy_returns_same_instance(self):
        """_get_connection() in legacy mode returns the cached module-level conn."""
        with _kanban_mode("legacy") as kb:
            conn1 = kb._get_connection()
            conn2 = kb._get_connection()
            assert conn1 is conn2, "Should return the same singleton connection"


# ── Public API completeness ──────────────────────────────────────────────────────


class TestPublicAPI:
    """Tests that the full public API is available from both engines."""

    def test_native_has_all_public_functions(self):
        """Native mode exports all expected public API functions."""
        import kanban as kb

        for name in PUBLIC_API:
            assert hasattr(kb, name), f"Native mode missing public API: {name}"

        from kanban_adapter import _db_path, _get_connection
        assert kb._db_path is _db_path
        assert kb._get_connection is _get_connection

    def test_legacy_has_all_public_and_legacy_functions(self):
        """Legacy mode exports all public API + legacy-only SQLite helpers."""
        with _kanban_mode("legacy") as kb:
            for name in PUBLIC_API:
                assert hasattr(kb, name), f"Legacy mode missing public API: {name}"

            for name in LEGACY_ONLY_API:
                assert hasattr(kb, name), f"Legacy mode missing legacy-only API: {name}"

    def test_engine_functions_are_distinct(self):
        """The same function name in native vs legacy points to different objects."""
        import kanban as kb

        native_fns = {}
        for name in ("advance", "create_parent", "scan_board", "promote"):
            native_fns[name] = getattr(kb, name)

        with _kanban_mode("legacy") as kb_l:
            for name in native_fns:
                assert getattr(kb_l, name) is not native_fns[name], (
                    f"{name} should be a different function object between modes"
                )

    def test_common_symbols_are_identical(self):
        """Shared symbols from kanban_common are the same object in both modes."""
        import kanban as kb

        from kanban_common import (
            AGENT_DESCRIPTIONS,
            MAX_CONVERGENCE_ROUNDS,
            NEXT_ACTION_STATUSES,
            _AGENT_VERB,
            _extract_target,
            child_id,
            parent_task_id,
        )

        # In native mode (default)
        assert kb._AGENT_VERB is _AGENT_VERB
        assert kb.AGENT_DESCRIPTIONS is AGENT_DESCRIPTIONS
        assert kb._extract_target is _extract_target
        assert kb.MAX_CONVERGENCE_ROUNDS is MAX_CONVERGENCE_ROUNDS
        assert kb.NEXT_ACTION_STATUSES is NEXT_ACTION_STATUSES
        assert kb.parent_task_id is parent_task_id
        assert kb.child_id is child_id

        # In legacy mode too
        with _kanban_mode("legacy") as kb_l:
            assert kb_l._AGENT_VERB is _AGENT_VERB
            assert kb_l.AGENT_DESCRIPTIONS is AGENT_DESCRIPTIONS
            assert kb_l._extract_target is _extract_target
            assert kb_l.MAX_CONVERGENCE_ROUNDS is MAX_CONVERGENCE_ROUNDS
            assert kb_l.NEXT_ACTION_STATUSES is NEXT_ACTION_STATUSES
            assert kb_l.parent_task_id is parent_task_id
            assert kb_l.child_id is child_id


# ── Config file reading ─────────────────────────────────────────────────────────


class TestConfigReading:
    """Tests for _get_kanban_mode() config file parsing edge cases."""

    def test_config_missing_key_defaults_to_native(self):
        """Missing 'kanban_mode' key defaults to 'native'."""
        import kanban as kb
        from kanban import _get_kanban_mode

        fake_config = "pipeline:\n  models:\n    defaults:\n      delegate:\n        model: test\n"
        with mock.patch.object(kb, "open", mock.mock_open(read_data=fake_config)):
            with mock.patch.object(kb.os.path, "isfile", return_value=True):
                mode = _get_kanban_mode()
        assert mode == "native", "Missing kanban_mode key should return 'native'"

    def test_config_file_not_found_defaults_to_native(self):
        """Missing config.yaml file defaults to 'native'."""
        import kanban as kb
        from kanban import _get_kanban_mode

        with mock.patch.object(kb.os.path, "isfile", return_value=False):
            mode = _get_kanban_mode()
        assert mode == "native", "Missing config file should return 'native'"

    def test_invalid_yaml_defaults_to_native(self):
        """Invalid YAML in config defaults to 'native'."""
        import kanban as kb
        from kanban import _get_kanban_mode

        with mock.patch.object(kb, "open", mock.mock_open(read_data="::: invalid yaml :::")):
            with mock.patch.object(kb.os.path, "isfile", return_value=True):
                mode = _get_kanban_mode()
        assert mode == "native", "Invalid YAML should return 'native'"

    def test_unknown_mode_value_defaults_to_native(self):
        """An unrecognized kanban_mode value defaults to 'native'."""
        import kanban as kb
        from kanban import _get_kanban_mode

        fake_config = "pipeline:\n  kanban_mode: unknown_value\n"
        with mock.patch.object(kb, "open", mock.mock_open(read_data=fake_config)):
            with mock.patch.object(kb.os.path, "isfile", return_value=True):
                mode = _get_kanban_mode()
        assert mode == "native", "Unknown mode value should return 'native'"
