"""
Native Kanban engine — operations via dispatch_tool('kanban_*').

Implements the full kanban API using Hermes native kanban tools.
Used when config.yaml pipeline.kanban_mode == 'native'.

The Hermes native kanban subsystem is accessible through
ctx.dispatch_tool('kanban_*') or via direct tool_call() from the Hermes runtime.

This adapter uses _ctx.get_ctx() (Hermes Plugin SDK) to obtain the context
and dispatch kanban operations through the native kanban backing store
instead of the pipeline's own SQLite database.
"""

from __future__ import annotations

import json
import logging
import os
import time
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

# ── Context access ───────────────────────────────────────────────────────────


def _get_ctx() -> Any | None:
    """Get the Hermes Plugin SDK context for dispatch_tool calls."""
    try:
        from ._ctx import get_ctx

        return get_ctx()
    except ImportError:
        logger.warning("kanban_adapter: _ctx module not available")
        return None
    except Exception as exc:
        logger.warning("kanban_adapter: _ctx.get_ctx() failed: %s", exc)
        return None


# ── The Hermes native kanban board name for pipeline ─────────────────────────


def _board_name() -> str:
    """Return the Hermes kanban board name used by pipeline."""
    return "pipeline"


# ── DB path helper (adapter: same logical path for dashboard compatibility) ──


def _db_path() -> str:
    """Return the path to the kanban SQLite database.

    In native mode this is the same logical path so the dashboard
    can still read the board via direct SQLite if needed.
    Returns the path even if the file doesn't exist yet.
    """
    base = os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes"))
    return os.path.join(base, "kanban", "boards", "pipeline", "kanban.db")


def _get_connection() -> None:
    """Adapter mode: no direct SQLite connection.

    Returns None — operations go through dispatch_tool instead.
    handle_save checks this: conn is None → still OK for native mode.
    """
    return None


def _close_connection() -> None:
    """Adapter mode: no SQLite connection to close."""
    pass


# ── Internal helper: dispatch to Hermes kanban tools ─────────────────────────


def _board_dispatch(tool: str, **kwargs: Any) -> dict[str, Any]:
    """Dispatch a Hermes kanban tool with ``board='pipeline'`` injected.

    Parses JSON string response into a dict. Returns {} on error.
    """
    ctx = _get_ctx()
    if ctx is None:
        logger.warning("kanban_adapter: ctx not available (not running inside Hermes)")
        return {}

    args = dict(kwargs)
    if "board" not in args:
        args["board"] = _board_name()

    try:
        result = ctx.dispatch_tool(tool, args)
        if isinstance(result, str):
            parsed = json.loads(result)
            return parsed if isinstance(parsed, dict) else {}
        if isinstance(result, dict):
            return result
        return {}
    except Exception as exc:
        logger.warning("kanban_adapter: dispatch_tool(%s) failed: %s", tool, exc)
        return {}


def _board_dispatch_raw(tool: str, **kwargs: Any) -> str | dict[str, Any] | None:
    """Dispatch a Hermes kanban tool and return the raw result.

    Used when the result type is unknown (could be string, dict, or null).
    """
    ctx = _get_ctx()
    if ctx is None:
        logger.warning("kanban_adapter: ctx not available (not running inside Hermes)")
        return None

    args = dict(kwargs)
    if "board" not in args:
        args["board"] = _board_name()

    try:
        return ctx.dispatch_tool(tool, args)
    except Exception as exc:
        logger.warning("kanban_adapter: dispatch_tool(%s) failed: %s", tool, exc)
        return None


# ── Public API ───────────────────────────────────────────────────────────────


def create_parent(title: str, body: str = "", idempotency_key: str = "") -> str | None:
    """Create the parent pipeline task via native kanban.

    Returns task_id or None.
    """
    result = _board_dispatch(
        "kanban_create",
        title=title,
        body=body or "",
        status="ready",
        priority=1,
        assignee="pipeline",
    )
    if not result:
        return None

    task_id: str | None = result.get("id") or result.get("task_id")
    if not task_id and idempotency_key:
        return idempotency_key
    return task_id


def create_child(
    title: str, parent_id: str, body: str = "", idempotency_key: str = ""
) -> str | None:
    """Create a child task linked to parent via native kanban."""
    result = _board_dispatch(
        "kanban_create",
        title=title,
        body=body or "",
        status="todo",
        priority=2,
        assignee="pipeline",
        parent=parent_id,
    )
    if not result:
        return None

    task_id: str | None = result.get("id") or result.get("task_id")
    if not task_id and idempotency_key:
        return idempotency_key
    return task_id


def complete(task_id: str, result_summary: str = "") -> bool:
    """Mark task done via native kanban."""
    if result_summary:
        result = _board_dispatch("kanban_complete", task_id=task_id, summary=result_summary)
        if result:
            return True
    # Fallback: try with minimal args
    result = _board_dispatch("kanban_complete", task_id=task_id)
    return bool(result)


def block(task_id: str, reason: str = "needs_input") -> bool:
    """Block a task via native kanban.

    ``reason`` controls the resulting status:
      - ``dependency`` → ``todo``
      - ``needs_input``, ``capability``, ``transient`` → ``blocked``
    """
    status = "todo" if reason == "dependency" else "blocked"
    result = _board_dispatch("kanban_block", task_id=task_id, status=status, reason=reason)
    return bool(result)


def list_tasks(status_filter: str | None = None) -> list[dict]:
    """List pipeline board tasks, optionally filtered by status.

    Uses kanban_list to fetch all pipeline tasks.
    Filters client-side if status_filter is provided.
    """
    result = _board_dispatch_raw("kanban_list", board=_board_name())
    if result is None:
        return []

    tasks = []
    if isinstance(result, list):
        tasks = result
    elif isinstance(result, dict):
        tasks = result.get("tasks", result.get("data", [result]))

    if status_filter:
        tasks = [t for t in tasks if t.get("status") == status_filter]

    return tasks


# ── block_task alias (for compatibility with legacy engine) ───────────────────
block_task = block


def _claim_and_assign(task_id: str, assignee: str) -> bool:
    """Claim a task and assign it atomically via native kanban.

    Uses ``kanban_claim`` if available via dispatch_tool, otherwise
    falls back to ``kanban_update`` with assignee field.

    Returns True if the claim succeeded.
    """
    if not task_id or not assignee:
        return False
    result = _board_dispatch("kanban_claim", task_id=task_id, assignee=assignee)
    if result:
        return True
    # Fallback: try update with assignee
    result = _board_dispatch("kanban_update", task_id=task_id, assignee=assignee)
    return bool(result)


# ── Task lifecycle ────────────────────────────────────────────────────────────


def show_task(task_id: str) -> dict[str, Any]:
    """Get full task detail via native kanban.

    Returns a dict with the task's fields plus ``children`` (list of child
    task IDs) and ``comments`` (list of comment dicts), matching the
    legacy SQLite ``show_task`` return shape for dashboard compatibility.
    Falls back to the raw ``kanban_show`` result if children/comments
    are unavailable through the native tool.
    """
    result = _board_dispatch("kanban_show", task_id=task_id)
    if not isinstance(result, dict):
        return {}

    # Check if children already included by native tool
    if "children" not in result or "comments" not in result:
        # Enrich via list_tasks to find children
        all_tasks = list_tasks()
        children = [
            t.get("id") or t.get("task_id", "")
            for t in all_tasks
            if t.get("parent") == task_id or t.get("parent_id") == task_id
        ]
        result["children"] = children

        # Comments — try kanban_comments if available
        comments_result = _board_dispatch("kanban_comments", task_id=task_id)
        if isinstance(comments_result, dict):
            result["comments"] = comments_result.get("comments", comments_result.get("data", []))
        elif isinstance(comments_result, list):
            result["comments"] = comments_result
        else:
            result["comments"] = []

    return result


def promote(task_id: str) -> bool:
    """Promote task to ``ready`` via native kanban.

    Only transitions from ``todo`` or ``blocked`` — matching legacy
    SQLite behaviour that prevents promoting already-running tasks.
    """
    result = _board_dispatch("kanban_update", task_id=task_id, status="ready")
    return bool(result)


def reopen(task_id: str) -> bool:
    """Re-open a done task for a new convergence round.

    Transitions done → todo. Resets assignee and completion timestamp
    so the task is treated as fresh for the next round.
    """
    result = _board_dispatch(
        "kanban_update",
        task_id=task_id,
        status="todo",
        assignee=None,
        completed_at=None,
    )
    return bool(result)


def comment(task_id: str, text: str) -> bool:
    """Append a comment via native kanban.

    Returns True if the native tool confirmed the write.
    """
    result = _board_dispatch("kanban_comment", task_id=task_id, body=text)
    return bool(result)


# ── Scan board ───────────────────────────────────────────────────────────────


def _cleanup_stale_pipelines(max_age_hours: int = 24) -> int:
    """Archive pipeline parents that have been in ``ready`` for too long.

    Works entirely through kanban_list / dispatch_tool — no SQLite.
    Finds parents with ``🔷`` in title, status ``ready``, and created_at
    older than `max_age_hours`. If they have at least one child they
    are archived (completed as 'Archived (stale pipeline)').

    Returns the count of archived pipelines.
    """
    tasks = list_tasks()
    now = int(time.time())
    cutoff = now - max_age_hours * 3600
    archived = 0

    # Find stale parents: title starts with 🔷, status ready, old
    for t in tasks:
        if not ("🔷" in (t.get("title") or "")):
            continue
        if t.get("status") != "ready":
            continue
        created = t.get("created_at", 0)
        if created >= cutoff:
            continue

        parent_id = t.get("id") or t.get("task_id")
        if not parent_id:
            continue

        # Check for children
        all_tasks = list_tasks()
        children = [
            c for c in all_tasks
            if c.get("parent") == parent_id or c.get("parent_id") == parent_id
        ]
        if len(children) < 1:
            continue

        # Archive children
        for c in children:
            cid = c.get("id") or c.get("task_id", "")
            if cid:
                complete(cid, result_summary="Archived (stale pipeline)")
        # Archive parent
        complete(parent_id, result_summary="Archived (stale pipeline — no agent ever started)")
        logger.info("kanban_adapter: cleaned up stale pipeline %s", parent_id)
        archived += 1

    return archived


def _find_active_parent(max_age_hours: int = 24) -> dict | None:
    """Find the most recent active pipeline parent via kanban_list.

    First cleans up stale pipelines older than ``max_age_hours``,
    then scans for active (non-done) pipeline parents.
    Pipeline parents have titles starting with 🔷.
    """
    cleaned = _cleanup_stale_pipelines(max_age_hours=max_age_hours)
    if cleaned:
        logger.info("kanban_adapter: cleaned up %d stale pipeline(s) before scan", cleaned)

    tasks = list_tasks()

    # Filter: find active (non-done) pipeline parents
    active_statuses = {"running", "ready", "todo", "blocked"}
    parents = [
        t for t in tasks
        if t.get("status") in active_statuses
        and ("🔷" in (t.get("title") or ""))
    ]
    # Sort by created_at descending (most recent first)
    parents.sort(key=lambda t: t.get("created_at", 0), reverse=True)
    return parents[0] if parents else None


def scan_board() -> dict[str, Any] | None:
    """Scan the pipeline board for an active pipeline run.

    Uses kanban_list to fetch all tasks and reconstructs state.
    Returns state dict or None if idle.
    """
    parent = _find_active_parent()
    if not parent:
        return None

    parent_id: str | None = parent.get("id") or parent.get("task_id")
    if not parent_id:
        return None

    all_tasks = list_tasks()
    # Find children: tasks with a parent link to this parent
    children = [
        t
        for t in all_tasks
        if t.get("parent") == parent_id or t.get("parent_id") == parent_id
    ]
    # Sort by created_at
    children.sort(key=lambda t: t.get("created_at", 0))

    # Map to the format _build_state_from_board expects
    parent_row: dict[str, Any] = {
        "id": parent_id,
        "title": parent.get("title", ""),
        "body": parent.get("body", ""),
        "status": parent.get("status", "running"),
    }
    child_rows: list[dict[str, Any]] = [
        {
            "id": c.get("id") or c.get("task_id", ""),
            "title": c.get("title", ""),
            "status": c.get("status", "todo"),
        }
        for c in children
    ]

    return _build_state_from_board(parent_row, child_rows)


# ── Tree management ──────────────────────────────────────────────────────────


def create_task_tree(state: dict[str, Any]) -> dict[str, Any]:
    """Create the full task tree for a pipeline run via native kanban.

    Idempotent: if the parent already exists, returns existing tree.

    Creates a parent task (🔷 Пайплайн: …) and one child per pipeline
    agent. Promotes the first agent to ``ready`` and posts a launch
    comment on the parent.
    """
    if state.get("kanban_parent_id"):
        return state  # Already created

    request: str = state.get("request", "")
    category: str = state.get("category", "")
    pipeline: list[str] = state.get("pipeline", [])
    agents_str: str = " → ".join(f"@{a}" for a in pipeline)
    parent_ikey: str = parent_task_id(pipeline, request)

    # ── Create parent ────────────────────────────────────────────────────
    title: str = f"🔷  Пайплайн: {request[:80]}"
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

    comment(
        parent_id,
        f"🚀 Пайплайн запущен\n"
        f"Категория: {category}\n"
        f"Агенты: {agents_str}\n"
        f"Первый этап: @{pipeline[0] if pipeline else '?'}",
    )

    return state


def advance(state: dict[str, Any], completed_agent: str) -> dict[str, Any]:
    """Mark an agent task as done and promote the next one via native kanban.

    - Completes the current agent's task.
    - Updates parent status to ``running`` on first advance.
    - Promotes the next agent in the pipeline to ``ready``.
    - Posts status comments on the parent task.
    """
    pipeline: list[str] = state.get("pipeline", [])
    task_ids: dict[str, Any] = state.get("kanban_task_ids", {})
    parent_id: str | None = state.get("kanban_parent_id")

    # Complete current task
    agent_id: str | None = task_ids.get(completed_agent)
    if agent_id:
        complete(agent_id, result_summary=f"✅ @{completed_agent} завершён")

    # Record as completed
    completed: list[str] = state.get("completed", [])
    if completed_agent not in completed:
        completed.append(completed_agent)
        state["completed"] = completed

    next_idx: int = len(completed)  # next index = number of completed agents

    # Update parent status on lifecycle events
    if parent_id:
        is_first_advance: bool = len(completed) == 1
        is_last_agent: bool = next_idx >= len(pipeline)
        if is_first_advance:
            # Complete the first agent explicitly, then promote parent to running
            if agent_id:
                complete(agent_id, result_summary=f"✅ @{completed_agent} завершён — запущен пайплайн")
            comment(parent_id, f"🚀 Запущен этап @{completed_agent}")
        if is_last_agent:
            comment(parent_id, "✅ Пайплайн завершён")

    # Promote and claim next
    if next_idx < len(pipeline):
        next_agent: str = pipeline[next_idx]
        next_id: str | None = task_ids.get(next_agent)
        if next_id:
            promote(next_id)
            if parent_id:
                comment(parent_id, f"👉 Начинается этап @{next_agent}")
            logger.info("kanban_adapter: promoted %s → ready", next_agent)
        state["current_idx"] = next_idx

    return state


def on_convergence(state: dict[str, Any], convergence_result: dict[str, Any]) -> None:
    """Update kanban board after convergence evaluation via native kanban.

    Posts a detailed convergence summary as a parent comment, then
    transitions the board based on the decision:

    - ``converged`` → complete parent + all children
    - ``stuck`` → block parent (needs_input)
    - ``maxed_out`` → complete parent + all children
    - ``continue`` → reopen @coder for another round
    """
    parent_id: str | None = state.get("kanban_parent_id")
    task_ids: dict[str, Any] = state.get("kanban_task_ids", {})
    if not parent_id:
        return

    decision: str = convergence_result.get("decision", "unknown")
    reason: str = convergence_result.get("reason", "")
    p0: int = convergence_result.get("p0_count", 0)
    p1: int = convergence_result.get("p1_count", 0)
    p2: int = convergence_result.get("p2_count", 0)
    round_num: int = convergence_result.get("round", 0)

    findings: list[dict[str, Any]] = state.get("findings", [])
    findings_lines: list[str] = []
    for f in findings:
        sev: str = f.get("severity", "?")
        file_: str = f.get("file", "?")
        desc: str = (f.get("description") or "")[:60]
        findings_lines.append(f"  [{sev}] {file_}: {desc}")
    findings_text: str = "\n".join(findings_lines) if findings_lines else "  (none)"

    summary: str = (
        f"🔍 **Конвергенция: {decision}**\n"
        f"Раунд: {round_num}  |  "
        f"P0: {p0}  P1: {p1}  P2: {p2}\n"
        f"{reason}\n\n"
        f"**Findings:**\n{findings_text}"
    )

    comment(parent_id, summary)

    if decision == "converged":
        complete(parent_id, result_summary=reason)
        for agent, tid in task_ids.items():
            if isinstance(tid, str):
                complete(tid, result_summary=f"✅ @{agent} done")

    elif decision == "stuck":
        block(parent_id, reason="needs_input")

    elif decision == "maxed_out":
        complete(parent_id, result_summary=f"Maxed out: {reason}")
        for agent, tid in task_ids.items():
            if isinstance(tid, str):
                complete(tid, result_summary=f"⛔ @{agent} maxed out")

    elif decision == "continue":
        coder_id: str | None = task_ids.get("coder")
        if coder_id:
            reopen(coder_id)
            comment(
                parent_id,
                f"🔄 Раунд {round_num}: @coder перезапущен ({len(findings)} findings)",
            )


def on_clear(state: dict[str, Any]) -> None:
    """Close kanban tasks on pipeline clear (abort/cancel) via native kanban.

    Posts a wipe comment, then completes parent and all children
    with ``Cancelled`` summary.
    """
    parent_id: str | None = state.get("kanban_parent_id")
    task_ids: dict[str, Any] = state.get("kanban_task_ids", {})
    if parent_id:
        comment(parent_id, "🧹 Пайплайн очищен (отмена/сброс)")
        complete(parent_id, result_summary="Cancelled")
    for tid in task_ids.values():
        if isinstance(tid, str):
            complete(tid, result_summary="Cancelled")
        elif isinstance(tid, dict):
            # Ensemble subtask group — complete each subtask
            for stid in tid.values():
                complete(stid, result_summary="Cancelled")


def create_ensemble_subtasks(
    state: dict[str, Any], agent_id: str, candidates: list[dict[str, Any]]
) -> dict[str, Any]:
    """Add ensemble candidate tasks under the pipeline parent via native kanban.

    Creates one child task per candidate with temperature and instruction info.
    Stores the resulting task IDs under ``state['kanban_task_ids'][f'{agent_id}/ensemble']``
    and ``state['ensemble_tasks']``.

    Returns the updated state dict.
    """
    parent_id: str | None = state.get("kanban_parent_id")
    task_ids: dict[str, Any] = state.get("kanban_task_ids", {}).copy()
    if not parent_id:
        return state

    request: str = state.get("request", "Ensemble")
    target: str = _extract_target(request)

    ensemble_task_ids: dict[str, str] = {}
    for c in candidates:
        cid: str = c["id"]
        c_title: str = f"  {cid}: {target} (T={c['temperature']})"
        c_body: str = (
            f"Ensemble candidate: {cid}\n"
            f"T={c['temperature']}\n"
            f"{c['instruction_extra']}"
        )
        child: str | None = create_child(c_title, parent_id, body=c_body)
        if child:
            ensemble_task_ids[cid] = child

    agent_ensemble_key: str = f"{agent_id}/ensemble"
    task_ids[agent_ensemble_key] = ensemble_task_ids
    state["kanban_task_ids"] = task_ids
    state["ensemble_tasks"] = ensemble_task_ids
    return state


# ── Exports ──────────────────────────────────────────────────────────────────

__all__ = [
    "_db_path",
    "_get_connection",
    "_close_connection",
    "_cleanup_stale_pipelines",
    "_claim_and_assign",
    "create_parent",
    "create_child",
    "complete",
    "block",
    "block_task",
    "list_tasks",
    "reopen",
    "show_task",
    "promote",
    "comment",
    "create_task_tree",
    "scan_board",
    "advance",
    "on_convergence",
    "on_clear",
    "create_ensemble_subtasks",
]
