# Pipeline Plugin — Баги

## Активные

| # | Severity | Описание | Файл | Статус |
|---|----------|----------|------|--------|
| — | — | Нет открытых багов в нашем коде | — | ✅ |
| — | P3 | test_scan_board_after_complete падает на dev (pre-existing) | tests/test_kanban_integration.py | ⚠️ |

## Задокументировано в ARCHITECTURE-FIXES.md

Все 20 багов (4 P0 + 7 P1 + 9 P2) пофикшены к v3.3.1.
См. [ARCHITECTURE-FIXES.md](./ARCHITECTURE-FIXES.md).

## Пофикшенные в v3.7.x

| # | Версия | Баг | Статус |
|---|--------|-----|--------|
| 1 | v3.7.2 | «аудит»/«audit» маппился в SECURITY_RELATED вместо REFACTORING | ✅ |
| 2 | v3.7.2 | `__init__.py` 892 строки — 17 хендлеров в одном файле | ✅ |
| — | v3.7.1 | Bandit B108, orchestrator skill quality gates | ✅ |
