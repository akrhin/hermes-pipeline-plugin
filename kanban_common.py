"""
Shared pipeline logic for kanban engines — no SQLite or dispatch_tool dependency.

Constants, helpers, _extract_target(), parent_task_id(), child_id(),
_build_state_from_board() and other state-reconstruction helpers.
"""

import hashlib
import json
import logging
import os
import re
import sqlite3
import threading
import uuid

logger = logging.getLogger(__name__)

# ── Module-level SQLite connection pool (moved from kanban.py) ───────────
_KANBAN_CONN: sqlite3.Connection | None = None
_KANBAN_LOCK = threading.Lock()

MAX_CONVERGENCE_ROUNDS = 3
NEXT_ACTION_STATUSES = {"ready", "todo"}

# ── Agent verb map ───────────────────────────────────────────────────────────

_AGENT_VERB: dict[str, str] = {
    "finder": "разведка",
    "analyst": "анализ",
    "researcher": "исследование",
    "architect": "архитектура",
    "planner": "план",
    "coder": "разработка",
    "editor": "правки",
    "fixer": "баг-фикс",
    "refactorer": "рефакторинг",
    "reviewer": "ревью",
    "security": "безопасность",
    "integration": "интеграция",
    "tester": "тесты",
    "debugger": "отладка",
    "documenter": "документация",
    "devops": "деплой",
    "optimizer": "оптимизация",
    "quality": "quality check",
}

# ── Role-specific task descriptions (shown in dashboard per agent) ──
AGENT_DESCRIPTIONS: dict[str, str] = {
    "finder": "Сбор информации: чтение кода, файлов, конфигов — разведка кодовой базы перед анализом",
    "analyst": "Анализ данных и диагностика: поиск корня проблемы, разбор логов, выявление закономерностей",
    "researcher": "Внешние исследования: поиск best practices, документация библиотек, альтернативные подходы",
    "architect": "Проектирование решения: архитектура изменений, выбор компонентов, связи между модулями",
    "planner": "Планирование: разбивка на подзадачи, оценка объёма работ, построение плана из шагов",
    "coder": "Разработка: написание кода, реализация фич, правка синтаксиса, имплементация логики",
    "editor": "Редактирование: правки по готовому плану, мелкие доработки, форматирование, типизация",
    "fixer": "Исправление: патчи известных багов, замена сломанных вызовов, обходы проблем",
    "refactorer": "Рефакторинг: улучшение структуры, устранение дублирования, выделение функций",
    "reviewer": "Код-ревью: проверка качества, поиск логических ошибок, рекомендации по улучшению",
    "security": "Аудит безопасности: XSS, SQL-инъекции, утечки данных, права доступа",
    "integration": "Консистентность: кросс-файловые связи, импорты, типы, совместимость API",
    "tester": "Тестирование: написание тестов, прогон, проверка регрессии, assertions",
    "debugger": "Отладка: шаг за шагом поиск первопричины, снятие стека, анализ переменных",
    "documenter": "Документация: README, AGENTS.md, комментарии в коде, changelog, инструкции",
    "devops": "Инфраструктура: CI/CD, Docker, деплой, системные юниты, мониторинг",
    "optimizer": "Оптимизация: производительность, память, асинхронность, кэширование, регрессия",
    "quality": "Quality gates: запуск ruff/bandit/compileall/pytest — проверка CI перед пушем",
}


# ── Helpers ──────────────────────────────────────────────────────────────────


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
        "hermes-pipeline-plugin",
        "pipeline-dashboard",
        "kanban.py",
        "server.py",
        "__init__.py",
        "models.py",
        "ensemble.py",
        "agents.md",
        "architecture.md",
        "config.yaml",
        "kanban.db",
        "pipeline",
        "plugin",
        "дашборд",
    ]
    req_lower = request.lower()
    for name in known:
        if name in req_lower:
            return name
    # 2. Файл после предлогов "в", "для", "на"
    m = re.search(r"\b(?:в|для|на)\s+(\S+(?:\.\w+)?)\b", request)
    if m:
        return m.group(1)
    # 3. Первое слово из 3+ букв без спецсимволов
    m = re.search(r"\b([а-яёa-z]{3,})\b", request.lower())
    if m:
        return m.group(1)
    return "проект"


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


def _parse_categories(body: str) -> tuple[list[str], str]:
    """Parse category list and primary category from body."""
    categories = []
    for line in body.split("\n"):
        if line.startswith("Категория:"):
            cat = line.split(":", 1)[1].strip()
            if cat:
                categories.append(cat)
        if line.startswith("Категории:"):
            for c in line.split(":", 1)[1].strip().split(","):
                c = c.strip()
                if c:
                    categories.append(c)
    return categories, categories[0] if categories else ""


def _parse_pipeline_order(body: str, children: list[dict]) -> list[str]:
    """Parse agent pipeline order from body, fallback to children titles."""
    for line in body.split("\n"):
        if line.startswith("Агенты:") or line.startswith("Агенты :"):
            agents_part = line.split(":", 1)[1].strip()
            return [
                a.strip().lstrip("@").strip()
                for a in agents_part.split("→")
                if a.strip()
            ]
    # Fallback: from child @-titles
    pipeline = []
    for child in children:
        ctitle = (child["title"] or "") if isinstance(child, dict) else ""
        if ctitle.startswith("@"):
            agent = ctitle.split(":", 1)[0].lstrip("@").strip()
            if agent:
                pipeline.append(agent)
    return pipeline


def _build_state_from_board(parent_row: dict, children: list[dict]) -> dict:
    """Reconstruct pipeline state dict from parent and children rows."""
    parent_id = parent_row["id"]
    title = parent_row["title"] or ""
    body = parent_row["body"] or ""
    parent_status = parent_row["status"]

    # Extract request from title/body
    request = title.replace("🔷  Пайплайн: ", "", 1)
    if "Запрос: " in body:
        request = body.split("Запрос: ", 1)[1]

    categories, category = _parse_categories(body)
    pipeline = _parse_pipeline_order(body, children)

    # Build task_ids and reconstruct completed/current_idx
    current_idx = -1
    completed = []
    task_ids = {}
    child_agents = {}
    for child in children:
        cid = child["id"]
        ctitle = (child["title"] or "")
        cstatus = (child["status"] or "")
        if ctitle.startswith("@"):
            agent = ctitle.split(":", 1)[0].lstrip("@").strip()
            if agent:
                child_agents[agent] = {"id": cid, "status": cstatus}

    for agent in pipeline:
        info = child_agents.get(agent)
        if info:
            task_ids[agent] = info["id"]
            if info["status"] == "done":
                completed.append(agent)
            elif info["status"] in ("ready", "todo", "running") and current_idx == -1:
                current_idx = pipeline.index(agent)

    return {
        "request": request,
        "category": category,
        "pipeline": pipeline,
        "current_idx": current_idx if current_idx >= 0 else 0,
        "completed": completed,
        "status": parent_status,
        "kanban_parent_id": parent_id,
        "kanban_task_ids": task_ids,
        "round": 0,
        "findings": _restore_findings_from_body(body),
    }


def _restore_findings_from_body(body: str) -> list[dict]:
    """Parse findings from kanban parent body.

    Если в body есть блок `#Findings:`, парсим findings из него.
    Это позволяет восстанавливать findings при pipeline_resume().
    """
    for line in body.split("\n"):
        line = line.strip()
        if line.startswith("#Findings:") or line.startswith("Findings:"):
            payload = line.split(":", 1)[1].strip()
            try:
                parsed = json.loads(payload)
                if isinstance(parsed, list):
                    return parsed
            except (json.JSONDecodeError, TypeError):
                pass
    return []


# ── SQLite helpers (from kanban.py) ─────────────────────────────────────────


def _db_path() -> str:
    """Return the path to the pipeline kanban.db file."""
    base = os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes"))
    return os.path.join(base, "kanban", "boards", "pipeline", "kanban.db")


def _get_connection() -> sqlite3.Connection | None:
    """Get or create a module-level SQLite connection.

    Uses a threading.Lock for thread safety and checks connection
    liveness with SELECT 1 before returning.
    """
    global _KANBAN_CONN
    with _KANBAN_LOCK:
        try:
            if _KANBAN_CONN is not None:
                _KANBAN_CONN.execute("SELECT 1")
                return _KANBAN_CONN
        except sqlite3.Error:
            _KANBAN_CONN = None

        db = _db_path()
        os.makedirs(os.path.dirname(db), exist_ok=True)
        conn = sqlite3.connect(db, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        _KANBAN_CONN = conn
        return conn


def _close_connection():
    """Close the module-level SQLite connection if open."""
    global _KANBAN_CONN
    with _KANBAN_LOCK:
        if _KANBAN_CONN is not None:
            try:
                _KANBAN_CONN.close()
            except Exception:
                pass
            _KANBAN_CONN = None


def _sqlite_select(query: str, params: tuple = ()) -> list[dict]:
    """Execute a SELECT query via the module-level SQLite connection."""
    conn = _get_connection()
    if conn is None:
        logger.warning("sqlite_select: no connection")
        return []
    try:
        cur = conn.execute(query, params)
        return [dict(row) for row in cur.fetchall()]
    except sqlite3.Error as exc:
        logger.warning("sqlite_select error: %s", exc)
        return []


def _sqlite_update(query: str, params: tuple = ()) -> bool:
    """Execute a write query via the module-level SQLite connection.

    Returns True if the operation succeeded and affected at least one row.
    """
    conn = _get_connection()
    if conn is None:
        logger.warning("sqlite_update: no connection")
        return False
    try:
        cur = conn.execute(query, params)
        conn.commit()
        return cur.rowcount > 0  # type: ignore[union-attr]
    except sqlite3.Error as exc:
        logger.warning("sqlite_update error: %s", exc)
        return False


def _claim_and_assign(task_id: str, assignee: str) -> bool:
    """Claim a task and assign it atomically via SQLite."""
    if not task_id or not assignee:
        return False
    ok = _sqlite_update(
        "UPDATE tasks SET assignee=?, claim_lock=1 WHERE id=? AND (assignee IS NULL OR assignee='')",
        (assignee, task_id),
    )
    return ok


def _update_parent_body(parent_id: str, state: dict) -> bool:
    """Update the parent task body with current pipeline state."""
    body = state.get("body", "")
    return _sqlite_update(
        "UPDATE tasks SET body=? WHERE id=?",
        (body, parent_id),
    )


def _update_parent_status(parent_id: str, status: str) -> bool:
    """Update the parent task status."""
    return _sqlite_update(
        "UPDATE tasks SET status=? WHERE id=?",
        (status, parent_id),
    )


__all__ = [
    "MAX_CONVERGENCE_ROUNDS",
    "NEXT_ACTION_STATUSES",
    "_AGENT_VERB",
    "AGENT_DESCRIPTIONS",
    "_extract_target",
    "parent_task_id",
    "child_id",
    "_parse_categories",
    "_parse_pipeline_order",
    "_build_state_from_board",
    "_restore_findings_from_body",
    "_db_path",
    "_get_connection",
    "_close_connection",
    "_sqlite_select",
    "_sqlite_update",
    "_claim_and_assign",
    "_update_parent_body",
    "_update_parent_status",
    "_KANBAN_CONN",
    "_KANBAN_LOCK",
]
