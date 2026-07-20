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
import logging
import os
import re
import sqlite3
import time
import uuid


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

MAX_CONVERGENCE_ROUNDS = 3
NEXT_ACTION_STATUSES = {"ready", "todo"}


def _extract_target(request: str) -> str:
    """Извлечь цель (проект/модуль/файл) из запроса для заголовка задачи.

    Приоритет:
    1. Упоминание файла (.py, .md, .yaml и т.д.)
    2. Упоминание проекта/плагина (hermes-pipeline-plugin, pipeline-dashboard, server.py и т.д.)
    3. Первое существительное после "в"/"для"
    """
    if not request:
        return "проект"
    # 1. Конкретные имена проектов/файлов (lowercase для case-insensitive сравнения)
    known = [
        "hermes-pipeline-plugin", "pipeline-dashboard", "kanban.py", "server.py",
        "__init__.py", "models.py", "ensemble.py", "agents.md", "architecture.md",
        "config.yaml", "kanban.db", "pipeline", "plugin", "дашборд",
    ]
    req_lower = request.lower()
    for name in known:
        if name in req_lower:
            return name
    # 2. Файл после предлогов "в", "для", "на"
    m = re.search(r'\b(?:в|для|на)\s+(\S+(?:\.\w+)?)\b', request)
    if m:
        return m.group(1)
    # 3. Первое слово из 3+ букв без спецсимволов
    m = re.search(r'\b([а-яёa-z]{3,})\b', request.lower())
    if m:
        return m.group(1)
    return "проект"


_AGENT_VERB: dict[str, str] = {
    "finder":     "разведка",
    "analyst":    "анализ",
    "researcher": "исследование",
    "architect":  "архитектура",
    "planner":    "план",
    "coder":      "разработка",
    "editor":     "правки",
    "fixer":      "баг-фикс",
    "refactorer": "рефакторинг",
    "reviewer":   "ревью",
    "security":   "безопасность",
    "integration":"интеграция",
    "tester":     "тесты",
    "debugger":   "отладка",
    "documenter": "документация",
    "devops":     "деплой",
    "optimizer":  "оптимизация",
}


# ── Role-specific task descriptions (shown in dashboard per agent) ──
# Расширенные описания (~x1.5 от кратких) — дают контекст: что делает, чем пользуется, какой результат
AGENT_DESCRIPTIONS: dict[str, str] = {
    "finder":     "Сбор информации: чтение кода, файлов, конфигов — разведка кодовой базы перед анализом",
    "analyst":    "Анализ данных и диагностика: поиск корня проблемы, разбор логов, выявление закономерностей",
    "researcher": "Внешние исследования: поиск best practices, документация библиотек, альтернативные подходы",
    "architect":  "Проектирование решения: архитектура изменений, выбор компонентов, связи между модулями",
    "planner":    "Планирование: разбивка на подзадачи, оценка объёма работ, построение плана из шагов",
    "coder":      "Разработка: написание кода, реализация фич, правка синтаксиса, имплементация логики",
    "editor":     "Редактирование: правки по готовому плану, мелкие доработки, форматирование, типизация",
    "fixer":      "Исправление: патчи известных багов, замена сломанных вызовов, обходы проблем",
    "refactorer": "Рефакторинг: улучшение структуры, устранение дублирования, выделение функций",
    "reviewer":   "Код-ревью: проверка качества, поиск логических ошибок, рекомендации по улучшению",
    "security":   "Аудит безопасности: XSS, SQL-инъекции, утечки данных, права доступа",
    "integration":"Консистентность: кросс-файловые связи, импорты, типы, совместимость API",
    "tester":     "Тестирование: написание тестов, прогон, проверка регрессии, assertions",
    "debugger":   "Отладка: шаг за шагом поиск первопричины, снятие стека, анализ переменных",
    "documenter": "Документация: README, AGENTS.md, комментарии в коде, changelog, инструкции",
    "devops":     "Инфраструктура: CI/CD, Docker, деплой, системные юниты, мониторинг",
    "optimizer":  "Оптимизация: производительность, память, асинхронность, кэширование, регрессия",
}


# ── DB path helper ──────────────────────────────────────────────────────────┘


def _db_path() -> str:
    """Return the path to the kanban SQLite database."""
    base = os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes"))
    return os.path.join(base, "kanban", "boards", "pipeline", "kanban.db")


# ── Public API ──────────────────────────────────────────────────────────────┘


def create_parent(title: str, body: str = "",
                  idempotency_key: str = "") -> str | None:
    """Create the parent pipeline task. Returns task_id or None."""
    task_id = idempotency_key or f"task:{uuid.uuid4().hex[:12]}"
    now = int(time.time())
    ok = _sqlite_update(
        "INSERT OR IGNORE INTO tasks (id, title, body, status, priority, created_at) VALUES (?, ?, ?, 'ready', 1, ?)",
        (task_id, title, body, now),
    )
    if not ok:
        # Task may already exist — try to fetch its id
        rows = _sqlite_select("SELECT id FROM tasks WHERE id=?", (task_id,))
        return rows[0]["id"] if rows else None
    logger.info("sqlite: created parent %s", task_id)
    return task_id


def create_child(title: str, parent_id: str, body: str = "",
                 idempotency_key: str = "") -> str | None:
    """Create a child task linked to parent. Returns task_id or None."""
    task_id = idempotency_key or f"task:{uuid.uuid4().hex[:12]}"
    now = int(time.time())
    ok = _sqlite_update(
        "INSERT OR IGNORE INTO tasks (id, title, body, status, priority, created_at) VALUES (?, ?, ?, 'todo', 2, ?)",
        (task_id, title, body, now),
    )
    if not ok:
        rows = _sqlite_select("SELECT id FROM tasks WHERE id=?", (task_id,))
        if rows:
            return rows[0]["id"]
        return None
    # Link child to parent
    _sqlite_update(
        "INSERT OR IGNORE INTO task_links (parent_id, child_id) VALUES (?, ?)",
        (parent_id, task_id),
    )
    logger.info("sqlite: created child %s under parent %s", task_id, parent_id)
    return task_id


def _sqlite_update(query: str, params: tuple = ()) -> bool:
    """Execute a write query on the kanban DB via direct SQLite."""
    if not query:
        return False
    db_path = _db_path()
    if not os.path.isfile(db_path):
        logger.warning("kanban DB not found: %s", db_path)
        return False
    try:
        conn = sqlite3.connect(db_path)
        try:
            conn.execute(query, params)
            conn.commit()
            return True
        finally:
            conn.close()
    except sqlite3.Error as exc:
        logger.warning("sqlite error: %s", exc)
        return False


def _sqlite_select(query: str, params: tuple = ()) -> list[dict]:
    """Execute a SELECT query and return rows as list of dicts."""
    db_path = _db_path()
    if not os.path.isfile(db_path):
        return []
    try:
        conn = sqlite3.connect(db_path)
        try:
            conn.row_factory = sqlite3.Row
            cur = conn.execute(query, params)
            return [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()
    except sqlite3.Error:
        return []


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
    """Append a comment via direct SQLite. Returns True if succeeded."""
    return _sqlite_update(
        "INSERT INTO task_comments (task_id, body, created_at, author) VALUES (?, ?, unixepoch(), ?)",
        (task_id, text, "pipeline-orchestrator"),
    )


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
        _sqlite_update(
            "INSERT INTO task_comments (task_id, body, created_at, author) VALUES (?, ?, unixepoch(), ?)",
            (task_id, result_summary, "pipeline-orchestrator"),
        )
    return ok


def block_task(task_id: str, reason: str = "",
               kind: str = "needs_input") -> bool:
    """Block a task via direct SQLite. Returns True if succeeded.

    ``kind`` controls the resulting status:
      - ``dependency`` → ``todo`` (auto-promoted by recompute_ready)
      - ``needs_input``, ``capability``, ``transient`` → ``blocked``
    """
    status = "todo" if kind == "dependency" else "blocked"
    return _sqlite_update(
        "UPDATE tasks SET status=?, block_kind=COALESCE(?, block_kind) WHERE id=?",
        (status, kind, task_id),
    )


def unblock(task_id: str) -> bool:
    """Unblock a task (for next convergence round). Needs --force."""
    return promote(task_id, force=True)


def list_tasks(status: str = "", include_archived: bool = False) -> list[dict]:
    """List tasks via direct SQLite, optionally filtered by status."""
    sql = "SELECT id, title, body, assignee, status, priority, created_by, created_at, started_at, completed_at, block_kind, block_recurrences FROM tasks WHERE 1=1"
    params: list[str] = []
    if status:
        sql += " AND status=?"
        params.append(status)
    if not include_archived:
        sql += " AND status!='archived'"
    sql += " ORDER BY created_at DESC"
    return _sqlite_select(sql, tuple(params))


def show_task(task_id: str) -> dict:
    """Get full task detail via direct SQLite (task + children + comments)."""
    rows = _sqlite_select("SELECT * FROM tasks WHERE id=?", (task_id,))
    if not rows:
        return {}
    task = rows[0]
    task["children"] = [
        r["child_id"] for r in _sqlite_select(
            "SELECT child_id FROM task_links WHERE parent_id=?", (task_id,)
        )
    ]
    task["comments"] = _sqlite_select(
        "SELECT * FROM task_comments WHERE task_id=? ORDER BY created_at ASC",
        (task_id,),
    )
    return task


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
    round_num = state.get("round", 0)
    target = _extract_target(request)
    for agent in pipeline:
        c_ikey = child_id(parent_ikey, agent, round_num)
        verb = _AGENT_VERB.get(agent, agent)
        c_title = f"@{agent}: {verb} {target}"
        desc = AGENT_DESCRIPTIONS.get(agent, request[:60])
        c_body = f"Этап: {agent}\nЗадача: {desc}\nОбъект: {target}\nЗапрос: {request}"
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
    now = int(time.time())
    return _sqlite_update(
        "UPDATE tasks SET status='running', assignee=COALESCE(assignee,?), "
        "started_at=COALESCE(started_at,?), last_heartbeat_at=? WHERE id=?",
        (assignee, now, now, task_id),
    )


def _update_parent_status(parent_id: str | None, status: str):
    """Update parent task status directly via SQLite."""
    if not parent_id:
        return
    import os, sqlite3
    db_path = _db_path()
    conn = None
    try:
        conn = sqlite3.connect(db_path)
        now = int(time.time())
        if status == "running":
            conn.execute(
                "UPDATE tasks SET status=?, started_at=COALESCE(started_at,?) WHERE id=?",
                (status, now, parent_id),
            )
        else:
            conn.execute(
                "UPDATE tasks SET status=?, completed_at=? WHERE id=?",
                (status, now, parent_id),
            )
        conn.commit()
    except sqlite3.Error as exc:
        logger.warning("sqlite error in _update_parent_status: %s", exc)
    finally:
        if conn:
            conn.close()


def advance(state: dict, completed_agent: str) -> dict:
    """Mark an agent task as done and promote the next one.

    Sets ``completed`` on the current agent, then promotes the next
    agent to ``ready`` and claims it into ``running`` with ``started_at``
    and an assignee so the dashboard can show meaningful lifecycle data.

    Updates the parent pipeline task status:
    - first advance  → parent becomes ``running``
    - all children done → parent becomes ``done``

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

    # Determine next index before parent status
    next_idx = current_idx + 1

    # Update parent status: running on first advance, done on last
    if parent_id:
        is_first_advance = len(completed) == 1  # first item just added
        is_last_agent = next_idx >= len(pipeline)
        if is_first_advance:
            _update_parent_status(parent_id, "running")
            comment(parent_id, f"🚀 Запущен этап @{completed_agent}")
        if is_last_agent:
            _update_parent_status(parent_id, "done")
            comment(parent_id, "✅ Пайплайн завершён")

    # Promote and claim next
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
    Only findings with status=open (or no status) count toward P0/P1.
    Findings with status='fixed', 'accepted', 'none' are ignored.
    Returns dict with decision/reason/counts.
    """
    if findings is not None:
        # Store new findings, compute fingerprint, bump round
        # Save current fingerprint as prev before computing new one
        curr_fp = state.get("findings_fingerprint", "")
        state["findings"] = findings
        state["findings_fingerprint"] = _compute_fingerprint(
            [f for f in findings if f.get("severity") in ("P0", "P1")
             and f.get("status", "open") not in ("fixed", "accepted", "none")]
        )
        state["prev_findings_fingerprint"] = curr_fp
        state["round"] = state.get("round", 0) + 1

    active_findings = state.get("findings", [])
    round_num = state.get("round", 0)
    max_rounds = state.get("max_rounds", MAX_CONVERGENCE_ROUNDS)

    # Filter: only count findings that are actually open
    open_findings = [
        f for f in active_findings
        if f.get("status", "open") not in ("fixed", "accepted", "none")
    ]
    p0 = [f for f in open_findings if f.get("severity") == "P0"]
    p1 = [f for f in open_findings if f.get("severity") == "P1"]
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
    # Find stale parents: pipeline parents in 'ready' older than cutoff
    stale = _sqlite_select(
        "SELECT id FROM tasks WHERE title LIKE '🔷%' AND status='ready' AND created_at < ?",
        (cutoff,),
    )
    archived = 0
    for row in stale:
        tid = row["id"]
        # Check that it really has children (a pipeline parent)
        children = _sqlite_select(
            "SELECT child_id FROM task_links WHERE parent_id=?", (tid,)
        )
        if len(children) < 2:
            continue
        # Archive all children first
        for c in children:
            complete(c["child_id"], result_summary="Archived (stale pipeline)")
        # Then archive the parent
        complete(tid, result_summary="Archived (stale pipeline — no agent ever started)")
        logger.info("cleaned up stale pipeline %s", tid)
        archived += 1
    return archived


def scan_board() -> dict | None:
    """Scan the pipeline board for an active pipeline run.

    Returns state dict reconstructed from kanban tasks, or None if idle.
    Uses direct SQLite instead of round-tripped list/show_task calls.

    Before scanning, archives any stale zombie pipelines that were
    created but never started (first promote silently failed pre-fix,
    or the session was reset before any agent ran).
    """
    # Garbage-collect stale pipelines before scanning
    cleaned = _cleanup_stale_pipelines(max_age_hours=24)  # Bug #4: мёртвые пайплайны накапливались
    if cleaned:
        logger.info("cleaned up %d stale pipeline(s) before scan", cleaned)

    # Find parents with children — pipeline parents in any active status
    parent_rows = _sqlite_select(
        "SELECT t.id, t.title, t.body, t.status, t.created_at "
        "FROM tasks t "
        "WHERE EXISTS (SELECT 1 FROM task_links l WHERE l.parent_id=t.id) "
        "AND t.status IN ('running','ready','todo','blocked') "
        "ORDER BY t.created_at DESC",
    )

    if not parent_rows:
        return None

    # Process the first (most recent) active parent
    t = parent_rows[0]
    parent_id = t["id"]
    title = t["title"] or ""
    body = t["body"] or ""
    parent_status = t["status"]

    # Get children via task_links + tasks join
    children = _sqlite_select(
        "SELECT c.id, c.title, c.status "
        "FROM tasks c "
        "JOIN task_links l ON l.child_id=c.id "
        "WHERE l.parent_id=? "
        "ORDER BY c.created_at ASC",
        (parent_id,),
    )

    # Extract request from title/body
    request = title.replace("🔷  Пайплайн: ", "", 1)
    if "Запрос: " in body:
        request = body.split("Запрос: ", 1)[1]

    # Extract category from body
    category = ""
    for line in body.split("\n"):
        if line.startswith("Категория:"):
            category = line.split(":", 1)[1].strip()

    # Reconstruct pipeline state
    current_idx = -1
    completed = []
    pipeline = []
    task_ids = {}
    for child in children:
        cid = child["id"]
        ctitle = child["title"] or ""
        cstatus = child["status"] or ""
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
        "status": parent_status,
        "kanban_parent_id": parent_id,
        "kanban_task_ids": task_ids,
        "round": 0,
        "findings": [],
    }
    return state


def get_agent_context(state: dict, agent_id: str) -> dict:
    """⚠️ DEPRECATED v3.0 — kept for backward compat.
    Use AGENT_CONTEXT_FIELDS in _build_agent_prompt() instead.
    Selective context routing is now handled in __init__.py._build_agent_prompt().
    """
    ctx = state.get("context", {})

    # Build agent-specific context
    agent_ctx = dict(ctx)  # shallow copy
    # Highlight the most relevant section
    if agent_id in ("coder", "fixer", "refactorer"):
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
    target = _extract_target(request)

    # Create a sub-task marker: agent_id+"/ensemble" under the main agent
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
