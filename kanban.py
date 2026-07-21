"""
Kanban-native pipeline state & convergence for Pipeline Plugin — ROUTER.

Reads config.yaml → pipeline.kanban_mode to select the kanban engine:

  - 'legacy' (default): direct SQLite via kanban_legacy.py
  - 'native':         Hermes native kanban tools via kanban_adapter.py

Re-exports all public functions + common symbols from both engines,
so callers and tests can continue using `import kanban as kb`.
"""

import logging
import os

logger = logging.getLogger(__name__)


# ── Utility: read kanban_mode from config.yaml ───────────────────────────────


def _get_kanban_mode() -> str:
    """Read `pipeline.kanban_mode` from config.yaml.

    Returns 'native' if the key is missing or unreadable.
    """
    try:
        import yaml  # type: ignore[import-untyped]

        # Resolve config path: same directory as this file (plugin root)
        config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.yaml")
        if os.path.isfile(config_path):
            with open(config_path, "r") as f:
                cfg = yaml.safe_load(f)
            mode = (cfg or {}).get("pipeline", {}).get("kanban_mode", "native")
            return mode if mode in ("legacy", "native") else "native"
    except Exception:
        pass
    return "native"


# Lazy-loaded kanban mode — None at import time, resolved on first access
_KANBAN_MODE: str | None = None


def get_kanban_mode() -> str:
    """Get the active kanban mode with lazy loading + caching.

    Uses a module-level cache so the config is read at most once.
    """
    global _KANBAN_MODE
    if _KANBAN_MODE is None:
        _KANBAN_MODE = _get_kanban_mode()
        logger.debug("kanban mode resolved: %s", _KANBAN_MODE)
    return _KANBAN_MODE


# ── Load engine ──────────────────────────────────────────────────────────────


if get_kanban_mode() == "native":
    # ── Native mode: Hermes kanban tools ─────────────────────────────────
    logger.info("kanban: using NATIVE mode (Hermes dispatch_tool)")

    from kanban_adapter import (
        _claim_and_assign,
        _cleanup_stale_pipelines,
        _close_connection,
        _db_path,
        _get_connection,
        advance,
        block,
        block_task,
        comment,
        complete,
        create_child,
        create_ensemble_subtasks,
        create_parent,
        create_task_tree,
        list_tasks,
        on_clear,
        on_convergence,
        promote,
        reopen,
        scan_board,
        show_task,
    )

    # All real implementations are now provided by kanban_adapter

else:
    # ── Legacy mode: direct SQLite (DEFAULT) ─────────────────────────────
    logger.info("kanban: using LEGACY mode (direct SQLite)")

    from kanban_legacy import (
        _claim_and_assign,
        _cleanup_stale_pipelines,
        _close_connection,
        _db_path,
        _find_active_parent,
        _get_connection,
        _sqlite_select,
        _sqlite_update,
        _update_parent_body,
        _update_parent_status,
        advance,
        block,
        block_task,
        comment,
        complete,
        create_child,
        create_ensemble_subtasks,
        create_parent,
        create_task_tree,
        list_tasks,
        on_clear,
        on_convergence,
        promote,
        reopen,
        scan_board,
        show_task,
    )
    from kanban_common import _KANBAN_CONN, _KANBAN_LOCK


# ── Common symbols (from kanban_common, shared by both engines) ────────────

# These are re-exported so callers can do `kanban._AGENT_VERB`, etc.
from kanban_common import (  # noqa: E402, F401  -- isort: skip
    _AGENT_VERB,
    _build_state_from_board,
    _extract_target,
    _parse_categories,
    _parse_pipeline_order,
    _restore_findings_from_body,
    AGENT_DESCRIPTIONS,
    child_id,
    MAX_CONVERGENCE_ROUNDS,
    NEXT_ACTION_STATUSES,
    parent_task_id,
)


# ── Debug/discovery helper ──────────────────────────────────────────────────


def _debug_mode() -> str:
    """Return the currently active kanban mode string (for diagnostics)."""
    return get_kanban_mode()


def _is_native_mode() -> bool:
    """Return True if the native (dispatch_tool) engine is active."""
    return get_kanban_mode() == "native"
