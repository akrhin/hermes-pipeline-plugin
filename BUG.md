# Pipeline Plugin — Баги

## Активные

| # | Severity | Описание | Файл | Статус |
|---|----------|----------|------|--------|
| — | — | Нет открытых багов в нашем коде | — | ✅ |
| — | P3 | test_scan_board_after_complete падает на dev (pre-existing) | tests/test_kanban_integration.py | ⚠️ |
| — | P3 | SQLite без WAL-mode — нет PRAGMA journal_mode=WAL при connect | kanban.py | ⚠️ |
| — | P3 | SQLite нет check_same_thread=False — race при threading | kanban.py | ⚠️ |
| — | P3 | `ensemble.py` import `_ctx` вместо `from _ctx` — сломается при pytest без mocker | ensemble.py | ⚠️ |
| — | P3 | `ensemble.py` import `retro` внутри `llm_judge_candidates` — late import | ensemble.py | ⚠️ |
| — | P3 | `kanban.py` — `sqlite3.connect` каждый вызов (нет connection pool) | kanban.py | ⚠️ |
| — | P3 | `_sqlite_select` молча возвращает [] при ошибке — диагностика невозможна | kanban.py | ⚠️ |
| — | P3 | `_sqlite_update` silent fail на любой ошибке — скрывает проблемы | kanban.py | ⚠️ |
| — | P4 | Нет тестов на `llm_judge_candidates()` — новый код без покрытия | ensemble.py | ⬜ |

## Задокументировано в ARCHITECTURE-FIXES.md

Все 20 багов (4 P0 + 7 P1 + 9 P2) пофикшены к v3.3.1.
См. [ARCHITECTURE-FIXES.md](./ARCHITECTURE-FIXES.md).

## Пофикшенные в v3.7.x

| # | Версия | Баг | Статус |
|---|--------|-----|--------|
| 1 | v3.7.2 | «аудит»/«audit» маппился в SECURITY_RELATED вместо REFACTORING | ✅ |
| 2 | v3.7.2 | `__init__.py` 892 строки — 17 хендлеров в одном файле | ✅ |
| — | v3.7.1 | Bandit B108, orchestrator skill quality gates | ✅ |
