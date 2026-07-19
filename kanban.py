"""
Kanban-native pipeline state & convergence for Pipeline Plugin.

Variant C: state.json removed — kanban.db is the single source of truth.

Board: pipeline (created once). Each pipeline run creates a task tree:
  Parent: "🔷 Pipeline: <request>"
  Children: @finder → @analyst → @researcher → @architect → @planner → @coder
            → @reviewer → @security → @integration → @tester → @documenter

Each child has a --parent link. Only one is in `ready` status at a time
(via `promote` when prior sibling completes).

Convergence: findings live in kanban comments on the parent task.
`evaluate_convergence()` reads findings from the parent comment,
computes deterministically (same algorithm as old state.py).
"""

import hashlib
import json
import logging
import subprocess
import time
from typing import Any


def _import_ensemble():
    """Import ensemble functions — works both as plugin and direct import."""
    try:
        from .ensemble import generate_candidates as gc
        from .ensemble import judge_candidates as jc
        return gc, jc
    except ImportError:
        from ensemble import generate_candidates as gc
        from ensemble import judge_candidates as jc
        return gc, jc


_ensemble_gen, _ensemble_judge = _import_ensemble()
ensemble_gen_candidates = _ensemble_gen
ensemble_judge_candidates = _ensemble_judge

logger = logging.getLogger(__name__)

BOARD = "pipeline"
KANBAN_TIMEOUT = 15
MAX_CONVERGENCE_ROUNDS = 3
NEXT_ACTION_STATUSES = {"ready", "todo"}


# ── Kanban CLI helpers ──────────────────────────────────────────────────────┘


def _kanban(*args: str) -> dict[str, Any]:
    """Run ``hermes kanban --board <BOARD> <args>``. Returns parsed JSON or {}.
    Callers MUST pass ``--json`` as part of *args* when they expect JSON output.
    ``--json`` is a per-command flag (not global), so placing it in the global
    prefix is an error — it must be after the subcommand.
    """
    cmd = ["hermes", "kanban", "--board", BOARD]
    cmd.extend(args)
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=KANBAN_TIMEOUT
        )
        if result.returncode != 0:
            logger.warning("kanban error (exit %d): %s", result.returncode,
                           result.stderr.strip()[:200])
            return {}
        out = result.stdout.strip()
        if not out:
            return {}
        try:
            return json.loads(out)
        except json.JSONDecodeError:
            return {"_text": out}
    except subprocess.TimeoutExpired:
        logger.warning("kanban command timed out")
        return {}
    except FileNotFoundError:
        logger.warning("hermes binary not found — kanban disabled")
        return {}
    except OSError as exc:
        logger.warning("kanban subprocess error: %s", exc)
        return {}


# ── Public API ──────────────────────────────────────────────────────────────┘


def create_parent(title: str, body: str = "",
                  idempotency_key: str = "") -> str | None:
    """Create the parent pipeline task. Returns task_id or None."""
    cmd = ["create", "--json", "--body", body, "--priority", "1", title]
    if idempotency_key:
        cmd.extend(["--idempotency-key", idempotency_key])
    result = _kanban(*cmd)
    return result.get("id") or None


def create_child(title: str, parent_id: str, body: str = "",
                 idempotency_key: str = "") -> str | None:
    """Create a child task linked to parent. Returns task_id or None."""
    cmd = ["create", "--json", "--body", body, "--parent", parent_id, "--priority", "2"]
    if idempotency_key:
        cmd.extend(["--idempotency-key", idempotency_key])
    cmd.append(title)
    result = _kanban(*cmd)
    return result.get("id") or None


def _sqlite_update(query: str, params: tuple = ()) -> bool:
    """Execute a write query on the kanban DB via direct SQLite."""
    if not query:
        return False
    import os
    import sqlite3
    db_path = os.path.expanduser("~/.hermes/kanban/boards/pipeline/kanban.db")
    if not os.path.isfile(db_path):
        logger.warning("kanban DB not found: %s", db_path)
        return False
    try:
        conn = sqlite3.connect(db_path)
        conn.execute(query, params)
        conn.commit()
        conn.close()
        return True
    except sqlite3.Error as exc:
        logger.warning("sqlite error: %s", exc)
        return False


def promote(task_id: str, force: bool = False) -> bool:
    """Promote task to ``ready`` via direct SQLite.

    ``force`` is accepted for backward compatibility but has no effect —
    direct SQLite has no parent-dependency gate.  The CLI ``promote``
    command (which does enforce gates) has been replaced because it
    silently returns ``{}`` when it fails (no error, no warning).
    """
    # Bug #1 + Bug #5: kanban promote CLI молча падает — прямой SQLite
    return _sqlite_update(
        "UPDATE tasks SET status='ready' WHERE id=? AND status IN ('todo','blocked')",
        (task_id,),
    )


def comment(task_id: str, text: str) -> bool:
    """Append a comment. Returns True if command succeeded."""
    return bool(_kanban("comment", task_id, text))


def complete(task_id: str, result_summary: str = "",
             metadata: dict | None = None) -> bool:
    """Mark task done via direct SQLite.

    ``result_summary`` and ``metadata`` are accepted for backward
    compatibility but stored as a comment (since kanban comments are the
    universal audit trail).  The CLI ``complete`` command silently
    returns ``{}`` on failure, so we now write directly to the DB.
    """
    # Bug #5: kanban complete CLI молча падает — прямой SQLite
    ok = _sqlite_update(
        "UPDATE tasks SET status='done', completed_at=unixepoch() WHERE id=? AND status!='done'",
        (task_id,),
    )
    if ok and result_summary:
        # Store result summary as a comment via DB (kanban comments table)
        import os
        import sqlite3
        db_path = os.path.expanduser("~/.hermes/kanban/boards/pipeline/kanban.db")
        try:
            conn = sqlite3.connect(db_path)
            now = int(time.time())
            conn.execute(
                "INSERT INTO task_comments (task_id, body, created_at, author) VALUES (?, ?, ?, ?)",
                (task_id, result_summary, now, "pipeline-orchestrator"),
            )
            conn.commit()
            conn.close()
        except (sqlite3.Error, OSError):
            pass  # Comment is optional, don't fail the complete
    return ok


def block_task(task_id: str, reason: str = "",
               kind: str = "needs_input") -> bool:
    """Block a task for human review. Returns True if command succeeded."""
    cmd = ["block", "--kind", kind, task_id]
    if reason:
        cmd.append(reason)
    return bool(_kanban(*cmd))


def unblock(task_id: str) -> bool:
    """Unblock a task (for next convergence round). Needs --force."""
    return promote(task_id, force=True)


def list_tasks(status: str = "", include_archived: bool = False) -> list[dict]:
    """List tasks, optionally filtered by status. Returns list of dicts."""
    cmd = ["ls", "--json"]
    if status:
        cmd.extend(["--status", status])
    if include_archived:
        cmd.extend(["--archived"])
    result = _kanban(*cmd)
    if isinstance(result, list):
        return result
    if "tasks" in result:
        return result["tasks"]
    return []


def show_task(task_id: str) -> dict:
    """Get full task detail (comments, children, etc.)."""
    result = _kanban("show", "--json", task_id)
    return result if isinstance(result, dict) else {}


def parent_task_id(pipeline: list[str], request: str = "") -> str:
    """Compute deterministic idempotency key from pipeline agent list + request.

    Including request in the hash prevents collision between two pipeline runs
    that use the same agent list (e.g. two security audits on different projects).
    """
    agents_str = "_".join(pipeline)
    base = f"{agents_str}:{request.strip()[:40]}"
    return f"pipe:{hashlib.md5(base.encode(), usedforsecurity=False).hexdigest()[:12]}"


def child_id(parent_ikey: str, agent: str, round_num: int = 0) -> str:
    """Deterministic idempotency key for a child task."""
    return f"{parent_ikey}:{agent}:r{round_num}"


# ── Tree management ─────────────────────────────────────────────────────────┘


def create_task_tree(state: dict) -> dict:
    """Create the full task tree for a pipeline run.

    Idempotent: if the parent already exists (via idempotency_key),
    subsequent calls return the existing tree structure without duplication.

    Returns state dict with kanban_task_ids populated.
    """
    if state.get("kanban_parent_id"):
        return state  # Already created

    request = state.get("request", "")
    category = state.get("category", "")
    pipeline = state.get("pipeline", [])
    agents_str = " → ".join(f"@{a}" for a in pipeline)
    parent_ikey = parent_task_id(pipeline, request)

    # ── Create parent ────────────────────────────────────────────────────
    title = f"🔷  Пайплайн: {request[:80]}"
    body = (
        f"Категория: {category}\n"
        f"Агенты: {agents_str}\n"
        f"Запрос: {request}"
    )
    parent_id = create_parent(title, body=body, idempotency_key=parent_ikey)
    if not parent_id:
        logger.warning("failed to create parent kanban task")
        return state

    state["kanban_parent_id"] = parent_id
    state["kanban_task_ids"] = {}  # agent → task_id

    # ── Create children ──────────────────────────────────────────────────
    for agent in pipeline:
        c_ikey = child_id(parent_ikey, agent)
        c_title = f"@{agent}: {request[:60]}"
        c_body = f"Этап: {agent}\nЗапрос: {request}"
        child_id_val = create_child(c_title, parent_id,
                                    body=c_body, idempotency_key=c_ikey)
        if child_id_val:
            state["kanban_task_ids"][agent] = child_id_val
            logger.info("created child task %s → %s", agent, child_id_val)

    # ── Promote first agent to ready ─────────────────────────────────────
    if pipeline:
        first_agent = pipeline[0]
        first_id = state["kanban_task_ids"].get(first_agent)
        if first_id:
            promote(first_id, force=True)
            _claim_and_assign(first_id, f"@{first_agent}")
            logger.info("promoted first agent %s → ready (assignee=%s)",
                        first_agent, first_agent)
    # ══ Log the pipeline start on the parent task ════════════════════════
    comment(parent_id,
            f"🚀 Пайплайн запущен\n"
            f"Категория: {category}\n"
            f"Агенты: {agents_str}\n"
            f"Первый этап: @{pipeline[0] if pipeline else '?'}")

    return state


def _claim_and_assign(task_id: str, assignee: str) -> bool:
    """Move a ``ready`` task to ``running`` and assign it.

    The kanban ``claim`` CLI requires a running daemon worker and
    silently fails when none is present (returns ``{}`` without
    ``claim_id``).  Since pipeline orchestrators do not (and should not)
    run a daemon, we write directly to the kanban DB — the same DB the
    pipeline dashboard reads via SQLite.

    Sets ``status`` → ``running``, ``assignee``, ``started_at``, and
    ``last_heartbeat_at`` so the dashboard can show meaningful lifecycle
    metadata.
    """
    # Bug #3: claim CLI молча не работает без daemon-воркера — используем прямой SQLite
    if not task_id or not assignee:
        return False
    import os
    import sqlite3
    db_path = os.path.expanduser("~/.hermes/kanban/boards/pipeline/kanban.db")
    if not os.path.isfile(db_path):
        logger.warning("kanban DB not found: %s", db_path)
        return False
    try:
        conn = sqlite3.connect(db_path)
        now = int(time.time())
        conn.execute(
            "UPDATE tasks SET status='running', assignee=COALESCE(assignee,?), "
            "started_at=COALESCE(started_at,?), last_heartbeat_at=? WHERE id=?",
            (assignee, now, now, task_id),
        )
        conn.commit()
        conn.close()
        logger.info(
            "sqlite: claimed+assigned %s → running (assignee=%s)", task_id, assignee
        )
        return True
    except sqlite3.Error as exc:
        logger.warning("sqlite error in _claim_and_assign: %s", exc)
        return False


def advance(state: dict, completed_agent: str) -> dict:
    """Mark an agent task as done and promote the next one.

    Sets ``completed`` on the current agent, then promotes the next
    agent to ``ready`` and claims it into ``running`` with ``started_at``
    and an assignee so the dashboard can show meaningful lifecycle data.

    Pipeline parents live in ``ready`` (never claimed by a daemon
    worker), so ``promote`` uses ``--force`` to bypass the parent-
    dependency gate.

    Returns state dict with updated current_idx.
    """
    pipeline = state.get("pipeline", [])
    task_ids = state.get("kanban_task_ids", {})
    parent_id = state.get("kanban_parent_id")
    current_idx = state.get("current_idx", 0)

    # Complete current task
    agent_id = task_ids.get(completed_agent)
    if agent_id:
        complete(agent_id, result_summary=f"✅ @{completed_agent} завершён")
    # Record as completed
    completed = state.get("completed", [])
    if completed_agent not in completed:
        completed.append(completed_agent)
        state["completed"] = completed

    # Promote and claim next
    next_idx = current_idx + 1
    if next_idx < len(pipeline):
        next_agent = pipeline[next_idx]
        next_id = task_ids.get(next_agent)
        if next_id:
            # Pipeline lifecycle: promote(todo→ready) then claim(ready→running)
            promote(next_id, force=True)
            _claim_and_assign(next_id, f"@{next_agent}")  # Bug #2: ранее claim не делался — started_at был пуст
            if parent_id:
                comment(parent_id, f"👉 Начинается этап @{next_agent}")
            logger.info("promoted+claimed %s → running (assignee=%s)", next_agent, next_agent)
        state["current_idx"] = next_idx

    return state


# ── Convergence (moved from state.py) ───────────────────────────────────────┘


def _compute_fingerprint(findings: list) -> str:
    """Hash P0/P1 findings for stuck detection. Same findings = same hash."""
    if not findings:
        return ""
    items = sorted(
        f"{f.get('severity', '')}:{f.get('file', '')}:"
        f"{f.get('category', '')}:{(f.get('description') or '')[:80]}"
        for f in findings
    )
    return hashlib.md5("|".join(items).encode(), usedforsecurity=False).hexdigest()[:12]


def evaluate_convergence(state: dict, findings: list | None = None) -> dict:
    """Evaluate pipeline convergence deterministically (no LLM).

    Mutates state with round/findings metadata.
    Returns dict with decision/reason/counts.
    """
    if findings is not None:
        # Store new findings, compute fingerprint, bump round
        # Save current fingerprint as prev before computing new one
        curr_fp = state.get("findings_fingerprint", "")
        state["findings"] = findings
        state["findings_fingerprint"] = _compute_fingerprint(
            [f for f in findings if f.get("severity") in ("P0", "P1")]
        )
        state["prev_findings_fingerprint"] = curr_fp
        state["round"] = state.get("round", 0) + 1

    active_findings = state.get("findings", [])
    round_num = state.get("round", 0)
    max_rounds = state.get("max_rounds", MAX_CONVERGENCE_ROUNDS)

    p0 = [f for f in active_findings if f.get("severity") == "P0"]
    p1 = [f for f in active_findings if f.get("severity") == "P1"]
    p2 = [f for f in active_findings if f.get("severity") == "P2"]
    p0p1 = list(p0) + list(p1)

    # No P0/P1 → converged
    if not p0p1:
        return {
            "decision": "converged",
            "reason": f"No P0/P1 findings ({len(p2)} P2 advisories)",
            "round": round_num,
            "p0_count": 0,
            "p1_count": 0,
            "p2_count": len(p2),
        }

    # Hard stop: max rounds with P0/P1 remaining
    if round_num >= max_rounds:
        return {
            "decision": "maxed_out",
            "reason": f"Reached max rounds ({max_rounds}) — "
                      f"{len(p0)} P0, {len(p1)} P1 unresolved",
            "round": round_num,
            "p0_count": len(p0),
            "p1_count": len(p1),
            "p2_count": len(p2),
        }

    # Stuck: same P0/P1 fingerprint as previous round
    current_fp = _compute_fingerprint(p0p1)
    prev_fp = state.get("prev_findings_fingerprint", "")
    if current_fp and current_fp == prev_fp:
        return {
            "decision": "stuck",
            "reason": f"Same {len(p0p1)} P0/P1 findings as previous round — "
                      "fixes are not converging",
            "round": round_num,
            "p0_count": len(p0),
            "p1_count": len(p1),
            "p2_count": len(p2),
        }

    # Continue
    return {
        "decision": "continue",
        "reason": f"{len(p0p1)} P0/P1 findings remain — "
                  f"round {round_num}/{max_rounds}",
        "round": round_num,
        "p0_count": len(p0),
        "p1_count": len(p1),
        "p2_count": len(p2),
    }


# ── Convergence via board ───────────────────────────────────────────────────┘


def on_convergence(state: dict, convergence_result: dict) -> None:
    """Update kanban board after convergence evaluation.

    - Comments with findings
    - Completes parent on converged/maxed_out
    - Blocks on stuck
    - Unblocks @coder for next round on continue
    """
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

    # Build findings summary
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

    if decision == "converged":
        metadata = {
            "decision": "converged",
            "round": round_num,
            "p0": p0, "p1": p1, "p2": p2,
        }
        complete(parent_id, result_summary=reason, metadata=metadata)
        # Close all child tasks too
        for agent, tid in task_ids.items():
            complete(tid, result_summary=f"✅ @{agent} done")

    elif decision == "stuck":
        block_task(parent_id,
                   reason=f"Stuck after round {round_num}: {reason}",
                   kind="needs_input")

    elif decision == "maxed_out":
        metadata = {
            "decision": "maxed_out",
            "round": round_num,
            "p0": p0, "p1": p1, "p2": p2,
        }
        complete(parent_id,
                 result_summary=f"Maxed out: {reason}",
                 metadata=metadata)

    elif decision == "continue":
        # Unblock @coder for next round
        coder_id = task_ids.get("coder")
        if coder_id:
            unblock(coder_id)
            comment(parent_id,
                    f"🔄 Раунд {round_num}: @coder перезапущен "
                    f"({len(findings)} findings)")


def on_clear(state: dict) -> None:
    """Close kanban tasks on pipeline clear (abort/cancel)."""
    parent_id = state.get("kanban_parent_id")
    task_ids = state.get("kanban_task_ids", {})
    if parent_id:
        comment(parent_id, "🧹 Пайплайн очищен (отмена/сброс)")
        complete(parent_id, result_summary="Cancelled")
    for tid in task_ids.values():
        complete(tid, result_summary="Cancelled")


# ── Resume from board ───────────────────────────────────────────────────────┘


def _cleanup_stale_pipelines(max_age_hours: int = 24) -> int:
    """Archive pipeline parents that have been in ``ready`` for too long.

    A pipeline parent in ``ready`` with no agent ever promoted to
    ``running`` is a stale zombie — it was created by ``pipeline_save``,
    the first promote silently failed (BUG #1 pre-fix), and no agent ever
    picked it up.  This function finds those and archives them so the
    dashboard stays clean.

    Returns the number of pipelines archived.
    """
    now = int(time.time())
    cutoff = now - max_age_hours * 3600
    all_tasks = list_tasks()
    archived = 0
    for t in all_tasks:
        tid = t.get("id", "")
        # Only pipeline parents: title starts with 🔷
        if not tid or not t.get("title", "").startswith("🔷"):
            continue
        if t.get("status") != "ready":
            continue
        created = t.get("created_at", 0) or 0
        if created > cutoff:
            continue  # too young
        # Check that it really has children (a pipeline parent)
        detail = show_task(tid)
        if len(detail.get("children", [])) < 2:
            continue
        # Archive all children first
        children_tasks = list_tasks(include_archived=True)
        child_ids = detail.get("children", [])
        for c in children_tasks:
            if c.get("id") in child_ids:
                complete(c["id"], result_summary="Archived (stale pipeline)")
        # Then archive the parent
        complete(tid, result_summary="Archived (stale pipeline — no agent ever started)")
        logger.info("cleaned up stale pipeline %s (created %d)", tid, created)
        archived += 1
    return archived


def scan_board() -> dict | None:
    """Scan the pipeline board for an active pipeline run.

    Returns state dict reconstructed from kanban tasks, or None if idle.
    Uses list() to find parents, then filters children by parent_task_ids.

    Before scanning, archives any stale zombie pipelines that were
    created but never started (first promote silently failed pre-fix,
    or the session was reset before any agent ran).
    """
    # Garbage-collect stale pipelines before scanning
    cleaned = _cleanup_stale_pipelines(max_age_hours=24)  # Bug #4: мёртвые пайплайны накапливались
    if cleaned:
        logger.info("cleaned up %d stale pipeline(s) before scan", cleaned)

    tasks = list_tasks(status="running")
    if not tasks:
        tasks = list_tasks(status="ready")
    if not tasks:
        tasks = list_tasks(status="todo")

    if not tasks:
        return None

    # Filter to only parent tasks (those with children on the board)
    parent_tasks = []
    for t in tasks:
        tid = t.get("id", "")
        if not tid:
            continue
        detail = show_task(tid)
        children = detail.get("children", [])
        if len(children) >= 2:  # A pipeline parent has 2+ children
            parent_tasks.append(t)

    if not parent_tasks:
        return None

    # Sort by created_at descending — prefer the most recent active pipeline
    parent_tasks.sort(key=lambda t: t.get("created_at", 0), reverse=True)

    # Find the first non-completed parent
    for t in parent_tasks:
        if t.get("status") in ("running", "ready", "todo", "blocked", "stuck",
                                "needs_input"):
            parent_id = t.get("id")
            if not parent_id:
                continue

            # Get all tasks to find children of this parent
            detail = show_task(parent_id)
            child_ids = detail.get("children", [])
            all_tasks = list_tasks(include_archived=True)
            children = [c for c in all_tasks if c.get("id") in child_ids]

            title = t.get("title", "")
            body = t.get("body", "")
            request = title.replace("🔷  Пайплайн: ", "", 1)  # Extract from title if not in body

            # Find request in body
            if "Запрос: " in body:
                request = body.split("Запрос: ", 1)[1]

            # Extract category from body
            category = ""
            for line in body.split("\n"):
                if line.startswith("Категория:"):
                    category = line.split(":", 1)[1].strip()

    # Find which child is ready/todo — use the FIRST one (lowest index)
            current_idx = -1
            completed = []
            pipeline = []
            task_ids = {}
            for idx, child in enumerate(children):
                cid = child.get("id", "")
                ctitle = child.get("title", "")
                cstatus = child.get("status", "")
                agent = ""
                if ctitle.startswith("@"):
                    agent = ctitle.split(":", 1)[0].lstrip("@").strip()
                if agent:
                    task_ids[agent] = cid
                    pipeline.append(agent)
                if cstatus == "done":
                    completed.append(agent)
                elif cstatus in ("ready", "todo", "running") and current_idx == -1:
                    if agent in pipeline:
                        current_idx = pipeline.index(agent)

            state = {
                "request": request,
                "category": category,
                "pipeline": pipeline,
                "current_idx": current_idx if current_idx >= 0 else 0,
                "completed": completed,
                "status": t.get("status", "running"),
                "kanban_parent_id": parent_id,
                "kanban_task_ids": task_ids,
                "round": 0,
                "findings": [],
            }
            return state

    return None


def get_agent_context(state: dict, agent_id: str) -> dict:
    """⚠️ DEPRECATED v3.0 — kept for backward compat.
    Use AGENT_CONTEXT_FIELDS in _build_agent_prompt() instead.
    Selective context routing is now handled in __init__.py._build_agent_prompt().
    """
    ctx = state.get("context", {})

    # Build agent-specific context
    agent_ctx = dict(ctx)  # shallow copy
    # Highlight the most relevant section
    if agent_id in ("coder", "editor", "fixer", "refactorer"):
        agent_ctx["_focus"] = "implementation"
    elif agent_id in ("reviewer", "security", "tester"):
        agent_ctx["_focus"] = "quality"
    elif agent_id == "documenter":
        agent_ctx["_focus"] = "documentation"
    elif agent_id == "devops":
        agent_ctx["_focus"] = "infrastructure"

    return agent_ctx


# ── Ensemble / Best-of-N ──────────────────────────────────────────────────────


def generate_candidates(state: dict, agent_id: str, n: int = 5) -> list[dict]:
    """Generate N candidate variations for ensemble execution.
    Delegates to ensemble.py for full implementation.
    """
    return ensemble_gen_candidates(state, agent_id, n)


def judge_candidates(request: str, candidates: list[dict],
                     judge_mode: str = "deterministic",
                     judge_config: dict | None = None) -> dict:
    """Select the best candidate from N results.
    Delegates to ensemble.py for full implementation.
    """
    return ensemble_judge_candidates(request, candidates, judge_mode, judge_config)


def create_ensemble_subtasks(state: dict, agent_id: str, candidates: list[dict]) -> dict:
    """Create N sub-tasks on the kanban board under the parent task."""
    parent_id = state.get("kanban_parent_id")
    task_ids = state.get("kanban_task_ids", {}).copy()
    if not parent_id:
        return state

    request = state.get("request", "Ensemble")

    # Create a sub-task marker: agent_id+"/ensemble" under the main agent
    ensemble_task_ids = {}
    for c in candidates:
        cid = c["id"]
        c_title = f"  {cid}: {request[:40]}"
        c_body = f"Ensemble candidate: {cid}\nT={c['temperature']}\n{c['instruction_extra']}"
        child = create_child(c_title, parent_id, body=c_body)
        if child:
            ensemble_task_ids[cid] = child

    agent_ensemble_key = f"{agent_id}/ensemble"
    task_ids[agent_ensemble_key] = ensemble_task_ids
    state["kanban_task_ids"] = task_ids
    state["ensemble_tasks"] = ensemble_task_ids
    return state
