"""
Legacy SQLite Kanban engine — direct sqlite3 access.

SQLite helpers (_sqlite_select, _sqlite_update) and connection management
are defined in kanban_common.py to avoid circular imports with kanban.py.
Tests that patch ``kanban_common._sqlite_select`` will also affect the legacy engine.
"""

import logging
import time
import uuid

from kanban_common import (
    _claim_and_assign,
    _close_connection,
    _db_path,
    _get_connection,
    _sqlite_select,
    _sqlite_update,
    _update_parent_body,
    _update_parent_status,
)
from kanban_common import (
    _AGENT_VERB,
    AGENT_DESCRIPTIONS,
    _build_state_from_board,
    _extract_target,
    child_id,
    parent_task_id,
)

logger = logging.getLogger(__name__)


# ── Internal helpers ─────────────────────────────────────────────────────────


def _cleanup_stale_pipelines(max_age_hours: int = 24) -> int:
    """Archive pipeline parents that have been in ``ready`` for too long."""
    now = int(time.time())
    cutoff = now - max_age_hours * 3600
    stale = _sqlite_select(
        "SELECT id FROM tasks WHERE title LIKE '🔷%' AND status='ready' AND created_at < ?",
        (cutoff,),
    )
    archived = 0
    for row in stale:
        tid = row["id"]
        children = _sqlite_select("SELECT child_id FROM task_links WHERE parent_id=?", (tid,))
        if len(children) < 1:
            continue
        for c in children:
            complete(c["child_id"], result_summary="Archived (stale pipeline)")
        complete(tid, result_summary="Archived (stale pipeline — no agent ever started)")
        logger.info("cleaned up stale pipeline %s", tid)
        archived += 1
    return archived


def _find_active_parent(max_age_hours: int = 24) -> dict | None:
    """Find the most recent active pipeline parent in the board."""
    cleaned = _cleanup_stale_pipelines(max_age_hours=max_age_hours)
    if cleaned:
        logger.info("cleaned up %d stale pipeline(s) before scan", cleaned)
    rows = _sqlite_select(
        "SELECT t.id, t.title, t.body, t.status, t.created_at "
        "FROM tasks t "
        "WHERE EXISTS (SELECT 1 FROM task_links l WHERE l.parent_id=t.id) "
        "AND t.status IN ('running','ready','todo','blocked') "
        "ORDER BY t.created_at DESC "
        "LIMIT 1",
    )
    return rows[0] if rows else None


# ── Public API ───────────────────────────────────────────────────────────────


def create_parent(title: str, body: str = "", idempotency_key: str = "") -> str | None:
    """Create the parent pipeline task. Returns task_id or None."""
    task_id = idempotency_key or f"task:{uuid.uuid4().hex[:12]}"
    now = int(time.time())
    ok = _sqlite_update(
        "INSERT OR IGNORE INTO tasks (id, title, body, status, priority, created_at)"
        " VALUES (?, ?, ?, 'ready', 1, ?)",
        (task_id, title, body, now),
    )
    if not ok:
        rows = _sqlite_select("SELECT id FROM tasks WHERE id=?", (task_id,))
        return rows[0]["id"] if rows else None
    logger.info("sqlite: created parent %s", task_id)
    return task_id


def create_child(
    title: str, parent_id: str, body: str = "", idempotency_key: str = ""
) -> str | None:
    """Create a child task linked to parent. Returns task_id or None."""
    task_id = idempotency_key or f"task:{uuid.uuid4().hex[:12]}"
    now = int(time.time())
    ok = _sqlite_update(
        "INSERT OR IGNORE INTO tasks (id, title, body, status, priority, created_at)"
        " VALUES (?, ?, ?, 'todo', 2, ?)",
        (task_id, title, body, now),
    )
    if not ok:
        rows = _sqlite_select("SELECT id FROM tasks WHERE id=?", (task_id,))
        if rows:
            return rows[0]["id"]
        return None
    _sqlite_update(
        "INSERT OR IGNORE INTO task_links (parent_id, child_id) VALUES (?, ?)",
        (parent_id, task_id),
    )
    logger.info("sqlite: created child %s under parent %s", task_id, parent_id)
    return task_id


def complete(task_id: str, result_summary: str = "") -> bool:
    """Mark task done via direct SQLite."""
    ok = _sqlite_update(
        "UPDATE tasks SET status='done', completed_at=unixepoch() WHERE id=? AND status!='done'",
        (task_id,),
    )
    if ok and result_summary:
        _sqlite_update(
            "INSERT INTO task_comments (task_id, body, created_at, author)"
            " VALUES (?, ?, unixepoch(), ?)",
            (task_id, result_summary, "pipeline-orchestrator"),
        )
    return ok


def block(task_id: str, reason: str = "needs_input") -> bool:
    """Block a task via direct SQLite."""
    status = "todo" if reason == "dependency" else "blocked"
    return _sqlite_update(
        "UPDATE tasks SET status=?, block_kind=COALESCE(?, block_kind) WHERE id=?",
        (status, reason, task_id),
    )


def reopen(task_id: str) -> bool:
    """Re-open a done task for a new convergence round."""
    return _sqlite_update(
        "UPDATE tasks SET status='todo', assignee=null, completed_at=null"
        " WHERE id=? AND status='done'",
        (task_id,),
    )


def show_task(task_id: str) -> dict:
    """Get full task detail via direct SQLite (task + children + comments)."""
    rows = _sqlite_select("SELECT * FROM tasks WHERE id=?", (task_id,))
    if not rows:
        return {}
    task = rows[0]
    task["children"] = [
        r["child_id"]
        for r in _sqlite_select("SELECT child_id FROM task_links WHERE parent_id=?", (task_id,))
    ]
    task["comments"] = _sqlite_select(
        "SELECT * FROM task_comments WHERE task_id=? ORDER BY created_at ASC",
        (task_id,),
    )
    return task


def promote(task_id: str) -> bool:
    """Promote task to ``ready`` via direct SQLite."""
    return _sqlite_update(
        "UPDATE tasks SET status='ready' WHERE id=? AND status IN ('todo','blocked')",
        (task_id,),
    )


def comment(task_id: str, text: str) -> bool:
    """Append a comment via direct SQLite."""
    return _sqlite_update(
        "INSERT INTO task_comments (task_id, body, created_at, author)"
        " VALUES (?, ?, unixepoch(), ?)",
        (task_id, text, "pipeline-orchestrator"),
    )


def list_tasks(status_filter: str | None = None) -> list[dict]:
    """List tasks, optionally filtered by status."""
    if status_filter:
        return _sqlite_select(
            "SELECT * FROM tasks WHERE status=? ORDER BY created_at DESC",
            (status_filter,),
        )
    return _sqlite_select("SELECT * FROM tasks ORDER BY created_at DESC")


# ── block_task alias ─────────────────────────────────────────────────────────

block_task = block


# ── Tree management ──────────────────────────────────────────────────────────


def create_task_tree(state: dict) -> dict:
    """Create the full task tree for a pipeline run."""
    if state.get("kanban_parent_id"):
        return state

    request = state.get("request", "")
    category = state.get("category", "")
    pipeline = state.get("pipeline", [])
    agents_str = " → ".join(f"@{a}" for a in pipeline)
    parent_ikey = parent_task_id(pipeline, request)

    title = f"🔷  Пайплайн: {request[:80]}"
    body = f"Категория: {category}\nАгенты: {agents_str}\nЗапрос: {request}"
    parent_id = create_parent(title, body=body, idempotency_key=parent_ikey)
    if not parent_id:
        logger.warning("failed to create parent kanban task")
        return state

    state["kanban_parent_id"] = parent_id
    state["kanban_task_ids"] = {}

    round_num = state.get("round", 0)
    target = _extract_target(request)
    for agent in pipeline:
        c_ikey = child_id(parent_ikey, agent, round_num)
        verb = _AGENT_VERB.get(agent, agent)
        c_title = f"@{agent}: {verb} {target}"
        desc = AGENT_DESCRIPTIONS.get(agent, request[:60])
        c_body = f"Этап: {agent}\nЗадача: {desc}\nОбъект: {target}\nЗапрос: {request}"
        child_id_val = create_child(c_title, parent_id, body=c_body, idempotency_key=c_ikey)
        if child_id_val:
            state["kanban_task_ids"][agent] = child_id_val
            logger.info("created child task %s → %s", agent, child_id_val)

    if pipeline:
        first_agent = pipeline[0]
        first_id = state["kanban_task_ids"].get(first_agent)
        if first_id:
            promote(first_id)
            _claim_and_assign(first_id, f"@{first_agent}")
            logger.info("promoted first agent %s → ready (assignee=%s)", first_agent, first_agent)

    comment(
        parent_id,
        f"🚀 Пайплайн запущен\n"
        f"Категория: {category}\n"
        f"Агенты: {agents_str}\n"
        f"Первый этап: @{pipeline[0] if pipeline else '?'}",
    )

    return state


def scan_board() -> dict | None:
    """Scan the pipeline board for an active pipeline run."""
    parent = _find_active_parent()
    if not parent:
        return None

    children = _sqlite_select(
        "SELECT c.id, c.title, c.status "
        "FROM tasks c "
        "JOIN task_links l ON l.child_id=c.id "
        "WHERE l.parent_id=? "
        "ORDER BY c.created_at ASC",
        (parent["id"],),
    )

    return _build_state_from_board(parent, children)


def advance(state: dict, completed_agent: str) -> dict:
    """Mark an agent task as done and promote the next one."""
    pipeline = state.get("pipeline", [])
    task_ids = state.get("kanban_task_ids", {})
    parent_id = state.get("kanban_parent_id")
    current_idx = state.get("current_idx", 0)

    agent_id = task_ids.get(completed_agent)
    if agent_id:
        complete(agent_id, result_summary=f"✅ @{completed_agent} завершён")

    completed = state.get("completed", [])
    if completed_agent not in completed:
        completed.append(completed_agent)
        state["completed"] = completed

    next_idx = current_idx + 1

    if parent_id:
        is_first_advance = len(completed) == 1
        is_last_agent = next_idx >= len(pipeline)
        if is_first_advance:
            _update_parent_status(parent_id, "running")
            comment(parent_id, f"🚀 Запущен этап @{completed_agent}")
        if is_last_agent:
            _update_parent_status(parent_id, "done")
            comment(parent_id, "✅ Пайплайн завершён")

    if next_idx < len(pipeline):
        next_agent = pipeline[next_idx]
        next_id = task_ids.get(next_agent)
        if next_id:
            promote(next_id)
            _claim_and_assign(next_id, f"@{next_agent}")
            if parent_id:
                comment(parent_id, f"👉 Начинается этап @{next_agent}")
            logger.info("promoted+claimed %s → running (assignee=%s)", next_agent, next_agent)
        state["current_idx"] = next_idx

    return state


def on_convergence(state: dict, convergence_result: dict) -> None:
    """Update kanban board after convergence evaluation."""
    parent_id = state.get("kanban_parent_id")
    task_ids = state.get("kanban_task_ids", {})
    if not parent_id:
        return

    decision = convergence_result.get("decision", "unknown")
    reason = convergence_result.get("reason", "")
    p0 = convergence_result.get("p0_count", 0)
    p1 = convergence_result.get("p1_count", 0)
    p2 = convergence_result.get("p2_count", 0)
    round_num = convergence_result.get("round", 0)

    findings = state.get("findings", [])
    findings_lines = []
    for f in findings:
        sev = f.get("severity", "?")
        file_ = f.get("file", "?")
        desc = (f.get("description") or "")[:60]
        findings_lines.append(f"  [{sev}] {file_}: {desc}")
    findings_text = "\n".join(findings_lines) if findings_lines else "  (none)"

    summary = (
        f"🔍 **Конвергенция: {decision}**\n"
        f"Раунд: {round_num}  |  "
        f"P0: {p0}  P1: {p1}  P2: {p2}\n"
        f"{reason}\n\n"
        f"**Findings:**\n{findings_text}"
    )

    comment(parent_id, summary)
    _update_parent_body(parent_id, state)

    if decision == "converged":
        complete(parent_id, result_summary=reason)
        for agent, tid in task_ids.items():
            complete(tid, result_summary=f"✅ @{agent} done")

    elif decision == "stuck":
        block(parent_id, reason="needs_input")

    elif decision == "maxed_out":
        complete(parent_id, result_summary=f"Maxed out: {reason}")
        for agent, tid in task_ids.items():
            complete(tid, result_summary=f"⛔ @{agent} maxed out")

    elif decision == "continue":
        coder_id = task_ids.get("coder")
        if coder_id:
            reopen(coder_id)
            comment(
                parent_id, f"🔄 Раунд {round_num}: @coder перезапущен ({len(findings)} findings)"
            )


def on_clear(state: dict) -> None:
    """Close kanban tasks on pipeline clear (abort/cancel)."""
    parent_id = state.get("kanban_parent_id")
    task_ids = state.get("kanban_task_ids", {})
    if parent_id:
        comment(parent_id, "🧹 Пайплайн очищен (отмена/сброс)")
        complete(parent_id, result_summary="Cancelled")
    for tid in task_ids.values():
        complete(tid, result_summary="Cancelled")
    _close_connection()


def create_ensemble_subtasks(state: dict, agent_id: str, candidates: list[dict]) -> dict:
    """Add ensemble candidate tasks under the pipeline parent."""
    parent_id = state.get("kanban_parent_id")
    task_ids = state.get("kanban_task_ids", {}).copy()
    if not parent_id:
        return state

    request = state.get("request", "Ensemble")
    target = _extract_target(request)

    ensemble_task_ids = {}
    for c in candidates:
        cid = c["id"]
        c_title = f"  {cid}: {target} (T={c['temperature']})"
        c_body = f"Ensemble candidate: {cid}\nT={c['temperature']}\n{c['instruction_extra']}"
        child = create_child(c_title, parent_id, body=c_body)
        if child:
            ensemble_task_ids[cid] = child

    agent_ensemble_key = f"{agent_id}/ensemble"
    task_ids[agent_ensemble_key] = ensemble_task_ids
    state["kanban_task_ids"] = task_ids
    state["ensemble_tasks"] = ensemble_task_ids
    return state
