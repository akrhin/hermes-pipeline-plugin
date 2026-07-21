"""
Native Kanban engine — operations via `hermes kanban` CLI.

Implements the full kanban API using Hermes native kanban CLI tools.
Used when config.yaml pipeline.kanban_mode == 'native'.

Uses subprocess to invoke `hermes kanban create/list/complete/...`
on the pipeline board. IMPORTANT: does NOT work with dispatch_tool('kanban_*')
because those tools are only available inside spawned workers, not
from plugin handler code.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import time
import uuid
from typing import Any

from kanban_common import (
    _AGENT_VERB,
    AGENT_DESCRIPTIONS,
    _build_state_from_board,
    _extract_target,
    child_id,
    parent_task_id,
)

logger = logging.getLogger(__name__)

# ── CLI helper ────────────────────────────────────────────────────────────────


def _kanban(*args: str, board: str = "pipeline") -> dict[str, Any]:
    """Run ``hermes kanban …`` on pipeline board and return parsed JSON.

    Args:
        *args: CLI arguments after ``hermes kanban`` (e.g. ``create``, ``list``).
        board: Board slug (default ``pipeline``).

    Returns:
        Parsed dict from the ``--json`` output, or ``{"status": "error",
        "stderr": …}`` on failure.
    """
    cmd = ["hermes", "kanban"]
    if board:
        cmd.extend(["--board", board])
    cmd.extend(args)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            logger.warning("kanban CLI error (%s): %s", " ".join(args), r.stderr[:200])
            return {"error": r.stderr.strip(), "status": "error"}
        stdout = r.stdout.strip()
        if stdout.startswith("{"):
            return json.loads(stdout)
        if stdout.startswith("["):
            loaded = json.loads(stdout)
            return {"tasks": loaded, "status": "ok"}
        # Non-JSON response — try wrapping
        return {"status": "ok", "raw": stdout}
    except subprocess.TimeoutExpired:
        logger.warning("kanban CLI timed out: %s", " ".join(args))
        return {"error": "timeout", "status": "error"}
    except Exception as exc:
        logger.warning("kanban CLI exception: %s", exc)
        return {"error": str(exc), "status": "error"}


# ── Interface functions ────────────────────────────────────────────────────────

_DB_PATH_CACHE: str | None = None


def _db_path() -> str:
    """Return the path to pipeline kanban DB (for compatibility with handlers).
    
    In native mode this path is not used for direct SQLite access, but
    handle_save checks it for non-native mode branch gating.
    """
    global _DB_PATH_CACHE
    if _DB_PATH_CACHE is not None:
        return _DB_PATH_CACHE
    base = os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes"))
    _DB_PATH_CACHE = os.path.join(base, "kanban", "boards", "pipeline", "kanban.db")
    return _DB_PATH_CACHE


def _get_connection() -> None:
    """Return None — no direct SQLite in native mode."""
    return None


def _close_connection() -> None:
    """No-op — no connection to close in native mode."""
    pass


def create_parent(title: str, body: str = "", idempotency_key: str = "") -> str | None:
    """Create a pipeline parent task via Hermes kanban CLI."""
    args = ["create", title[:120], "--body", body[:500], "--priority", "2",
            "--assignee", "pipeline"]
    if idempotency_key:
        args.extend(["--idempotency-key", idempotency_key])
    result = _kanban(*args)
    if result.get("status") == "error":
        logger.warning("create_parent failed: %s", result.get("error"))
        return None
    # Try various response shapes
    task_id = result.get("id") or result.get("task_id")
    if not task_id and isinstance(result.get("raw"), str) and "id=" in result["raw"]:
        # Fallback: parse from human-readable output
        return None
    return task_id


def create_child(title: str, parent_id: str, body: str = "",
                 idempotency_key: str = "") -> str | None:
    """Create a child task under the parent."""
    args = ["create", title[:120], "--body", body[:500], "--priority", "2",
            "--assignee", "pipeline", "--parent", parent_id]
    if idempotency_key:
        args.extend(["--idempotency-key", idempotency_key])
    result = _kanban(*args)
    if result.get("status") == "error":
        logger.warning("create_child failed: %s", result.get("error"))
        return None
    return result.get("id") or result.get("task_id")


def complete(task_id: str, result_summary: str = "") -> bool:
    """Mark a kanban task as completed."""
    if not task_id:
        return False
    args = ["complete", task_id]
    if result_summary:
        args.extend(["--summary", result_summary[:500]])
    result = _kanban(*args)
    if result.get("status") == "error":
        logger.warning("complete failed: %s", result.get("error"))
        return False
    return True


def block(task_id: str, reason: str = "needs_input") -> bool:
    """Block a kanban task."""
    if not task_id:
        return False
    if reason in ("dependency", "waiting"):
        # Dependencies go to todo (not blocked)
        result = _kanban("update", task_id, "--status", "todo")
    else:
        result = _kanban("block", task_id, "--reason", reason[:200])
    return result.get("status") != "error"


def block_task(task_id: str, reason: str = "needs_input") -> bool:
    """Alias for block()."""
    return block(task_id, reason)


def promote(task_id: str) -> bool:
    """Move a task to ready (promote from todo)."""
    if not task_id:
        return False
    result = _kanban("update", task_id, "--status", "ready")
    return result.get("status") != "error"


def reopen(task_id: str) -> bool:
    """Reopen a completed task for another convergence round."""
    if not task_id:
        return False
    result = _kanban("update", task_id, "--status", "todo", "--unassign")
    return result.get("status") != "error"


def comment(task_id: str, text: str) -> bool:
    """Post a comment on a kanban task."""
    if not task_id or not text:
        return False
    result = _kanban("comment", task_id, "--body", text[:1000])
    return result.get("status") != "error"


def show_task(task_id: str) -> dict[str, Any]:
    """Get task details via kanban CLI."""
    if not task_id:
        return {}
    result = _kanban("show", task_id)
    if result.get("status") == "error":
        return {}
    # If result has tasks key from list wrapping
    if "tasks" in result:
        return result["tasks"][0] if result["tasks"] else {}
    return result


def list_tasks(status_filter: str | None = None) -> list[dict[str, Any]]:
    """List tasks on the pipeline board, optionally filtered by status."""
    args = ["list"]
    if status_filter:
        args.extend(["--status", status_filter])
    result = _kanban(*args)
    if result.get("status") == "error":
        return []
    if "tasks" in result:
        return result["tasks"]
    # May be list directly if output started with [
    if isinstance(result, list):
        return result
    # Single task wrapped
    return [result] if result.get("id") else []


# ── Pipeline handlers ──────────────────────────────────────────────────────────

_FIRST_AGENT_PROMOTED: set[str] = set()


def create_task_tree(state: dict[str, Any]) -> dict[str, Any]:
    """Create the full task tree for a pipeline run via Hermes kanban CLI.

    Idempotent: if the parent already exists (by idempotency key), returns existing tree.
    """
    if state.get("kanban_parent_id"):
        return state  # Already created

    request: str = state.get("request", "")
    category: str = state.get("category", "")
    pipeline: list[str] = state.get("pipeline", [])
    agents_str: str = " → ".join(f"@{a}" for a in pipeline)
    parent_ikey: str = parent_task_id(pipeline, request)

    # ── Create parent ────────────────────────────────────────────────────
    title: str = f"🔷 Пайплайн: {request[:80]}"
    body: str = f"Категория: {category}\nАгенты: {agents_str}\nЗапрос: {request}"
    parent_id: str | None = create_parent(title, body=body, idempotency_key=parent_ikey)
    if not parent_id:
        logger.warning("kanban_adapter: failed to create parent task")
        return state

    state["kanban_parent_id"] = parent_id
    state["kanban_task_ids"] = {}

    # ── Create children ──────────────────────────────────────────────────
    round_num: int = state.get("round", 0)
    target: str = _extract_target(request)
    for agent in pipeline:
        c_ikey: str = child_id(parent_ikey, agent, round_num)
        verb: str = _AGENT_VERB.get(agent, agent)
        c_title: str = f"@{agent}: {verb} {target}"
        desc: str = AGENT_DESCRIPTIONS.get(agent, request[:60])
        c_body: str = (
            f"Этап: {agent}\n"
            f"Задача: {desc}\n"
            f"Объект: {target}\n"
            f"Запрос: {request}"
        )
        child_id_val: str | None = create_child(
            c_title, parent_id, body=c_body, idempotency_key=c_ikey
        )
        if child_id_val:
            state["kanban_task_ids"][agent] = child_id_val
            logger.info("kanban_adapter: created child %s → %s", agent, child_id_val)

    # ── Promote first agent to ready ─────────────────────────────────────
    if pipeline:
        first_agent: str = pipeline[0]
        first_id: str | None = state["kanban_task_ids"].get(first_agent)
        if first_id:
            promote(first_id)
            _FIRST_AGENT_PROMOTED.add(first_id)

    comment(parent_id, f"🚀 Пайплайн запущен {' → '.join(f'@{a}' for a in pipeline)}")
    logger.info("kanban_adapter: created task tree parent=%s %d children",
                parent_id, len(state["kanban_task_ids"]))
    return state


def advance(state: dict[str, Any], completed_agent: str) -> dict[str, Any]:
    """Mark agent done, promote next."""
    state = dict(state)
    parent_id: str | None = state.get("kanban_parent_id")
    task_ids: dict[str, str] = state.get("kanban_task_ids", {})
    pipeline: list[str] = state.get("pipeline", [])
    completed: list[str] = list(state.get("completed", []))
    current_idx: int = state.get("current_idx", 0)

    # Complete current agent task
    tid = task_ids.get(completed_agent) or task_ids.get(f"@{completed_agent}")
    if tid:
        complete(tid, result_summary=f"@{completed_agent} completed")

    # Update state
    if completed_agent not in completed:
        completed.append(completed_agent)
    next_idx = current_idx + 1

    # Promote next agent if any
    if next_idx < len(pipeline):
        next_agent = pipeline[next_idx]
        next_tid = task_ids.get(next_agent) or task_ids.get(f"@{next_agent}")
        if next_tid:
            promote(next_tid)
            comment(parent_id or "", f"✅ @{completed_agent} → @{next_agent}")
    else:
        # All agents done
        if parent_id:
            complete(parent_id, result_summary="All agents completed")
            comment(parent_id, "✅ Пайплайн выполнен")

    # Update parent status
    if parent_id:
        _kanban("update", parent_id, "--status",
                "running" if next_idx < len(pipeline) else "done")

    state["completed"] = completed
    state["current_idx"] = next_idx
    return state


def scan_board() -> dict[str, Any] | None:
    """Scan the pipeline board for an active pipeline run.

    Returns reconstructed state or None.
    """
    # Find active (non-closed) parent with 🔷 prefix
    tasks = list_tasks(status_filter="ready,running,todo")
    for t in tasks:
        title = t.get("title", "")
        tid = t.get("id", "")
        if "🔷" in title or "Пайплайн" in title:
            # Found pipeline parent — get full detail
            detail = show_task(tid)
            children = detail.get("children", [])
            child_details: list[dict] = []
            for cid in children:
                cd = show_task(cid)
                child_details.append(cd) if cd else None
            state = _build_state_from_board(detail, child_details)
            if state:
                return state
    return None


def on_clear(state: dict[str, Any]) -> None:
    """Close kanban tasks on pipeline clear (abort/cancel)."""
    parent_id: str | None = state.get("kanban_parent_id")
    task_ids: dict[str, Any] = state.get("kanban_task_ids", {})
    if parent_id:
        comment(parent_id, "🧹 Пайплайн очищен (отмена/сброс)")
        complete(parent_id, result_summary="Cancelled")
    for tid in task_ids.values():
        if isinstance(tid, str):
            complete(tid, result_summary="Cancelled")
        elif isinstance(tid, dict):
            for subtid in tid.values():
                complete(subtid, result_summary="Cancelled")


def on_convergence(state: dict[str, Any], convergence_result: dict[str, Any]) -> None:
    """Update kanban board after convergence evaluation."""
    parent_id: str | None = state.get("kanban_parent_id")
    decision: str = convergence_result.get("decision", "continue")
    reason: str = convergence_result.get("reason", "")

    if not parent_id:
        return

    summary = f"🔄 Конвергенция: {decision}\n{reason}"
    comment(parent_id, summary)

    if decision in ("converged", "maxed_out"):
        # Complete parent + all children
        task_ids = state.get("kanban_task_ids", {}).copy()
        for _agent, tid in task_ids.items():
            if isinstance(tid, str):
                complete(tid, result_summary=f"Convergence: {decision}")
        complete(parent_id, result_summary=f"Convergence: {decision}")
    elif decision == "stuck":
        block(parent_id, reason="stuck")
    # 'continue' — nothing to close, new round will create new tasks


def create_ensemble_subtasks(state: dict[str, Any], agent_id: str,
                              candidates: list[dict[str, Any]]) -> dict[str, Any]:
    """Add ensemble candidate tasks under the pipeline parent."""
    parent_id = state.get("kanban_parent_id")
    task_ids = state.get("kanban_task_ids", {}).copy()
    if not parent_id:
        return state

    request = state.get("request", "Ensemble")
    target = _extract_target(request)
    subtask_ids: dict[str, str] = {}
    for i, cand in enumerate(candidates, 1):
        title = f"@{agent_id}: кандидат {i} {target}"
        body = (f"Ensemble candidate {i}/{len(candidates)}\n"
                f"Температура: {cand.get('temperature', '?')}\n"
                f"Инструкция: {cand.get('instruction_extra', '—')}\n"
                f"Запрос: {request}")
        cid = create_child(title, parent_id, body=body)
        if cid:
            subtask_ids[cand.get("id", str(i))] = cid
    task_ids[agent_id] = subtask_ids
    state["kanban_task_ids"] = task_ids
    return state


def _cleanup_stale_pipelines(max_age_hours: int = 24) -> int:
    """Archive stale pipelines via kanban CLI."""
    return 0  # Stale cleanup is handled by gateway dispatcher


def _claim_and_assign(task_id: str, assignee: str) -> bool:
    """Claim and assign a task — native kanban manages this via dispatcher."""
    if not task_id or not assignee:
        return False
    return True


# ── Module API ────────────────────────────────────────────────────────────────

__all__ = [
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
]
