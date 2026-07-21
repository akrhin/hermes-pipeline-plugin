# План оптимизации архитектуры Pipeline Plugin v3.8.2

**Дата:** 2026-07-21
**Основание:** CRG MCP анализ графа (267 нод, 2032 ребра, 9 комьюнити)

---

## Этап 1: 🔴 Быстрые исправления (безопасно, пофиксить в 1 прогон)

| # | Задача | Файл | CRG метрика | Статус |
|---|--------|------|-------------|--------|
| 1 | Починить `test_kanban_integration._has_kanban()` — заменить проверку Hermes CLI на прямую проверку SQLite БД | `tests/test_kanban_integration.py` | bridge: test_scan_board_roundtrip (0.032) — **always skip** | ⏳ |
| 2 | ~~Удалить dead code: `kanban.py` строки 822–919 (97 строк unreachable после return) — 10× F821~~ | ✅ **v3.8.2 — выполнено** | Ruff 0 | ✅ |
| 3 | Исправить 2 E501 (line > 100) в `classify.py` | `classify.py` | ruff | ⏳ |
| 4 | Убрать `pre_tool_call` из `plugin.yaml::provides_hooks` (не реализован) | `plugin.yaml` | non-functional hook | ⏳ |
| 5 | Исправить CHANGELOG.md — убрать «4 879 тестов» (ложные данные) | `CHANGELOG.md` | дезинформация | ⏳ |

## Этап 2: 🟡 Рефакторинг god functions (средний риск)

| # | Задача | Текущий | Цель | Статус |
|---|--------|---------|------|--------|
| 6 | Разбить `kanban.py::scan_board` (135 строк) на 3-4 подфункции | deg 40, untested | ≤50 строк на функцию | ⏳ |
| 7 | Разбить `__init__.py::handle_run_agent` (110 строк) | deg 25, untested | ≤50 строк | ⏳ |
| 8 | Разбить `retro.py::_build_metrics_sections` (72 строки) | deg 39 | ≤50 строк | ⏳ |
| 9 | Разбить `ensemble.py::judge_candidates` + `llm_judge_candidates` (64+74 стр) | deg 26 | ≤50 строк | ⏳ |
| 10 | Разбить `convergence.py::evaluate_convergence` (74 строки) | deg 30 | ≤50 строк | ⏳ |

## Этап 3: 🟡 Тесты на untested hotspots (средний риск)

| # | Функция | deg | Файл | Статус |
|---|---------|-----|------|--------|
| 11 | `render` — 76 связей, 0 тестов | 76 | tools/retro-summary | ⏳ |
| 12 | `_analyze` — 42 связи, 0 тестов | 42 | tools/retro-summary | ⏳ |
| 13 | `scan_board` — 40 связей, тесты сломаны | 40 | kanban.py | ⏳ |
| 14 | `_build_metrics_sections` — 39 связей, 0 тестов | 39 | retro.py | ⏳ |
| 15 | `handle_convergence` — 37 связей, 0 тестов | 37 | handlers/__init__.py | ⏳ |
| 16 | `evaluate_convergence` — 30 связей, 0 тестов | 30 | convergence.py | ⏳ |

## Этап 4: 🟢 Документация и CI

| # | Задача | Статус |
|---|--------|--------|
| 17 | ~~Обновить `AGENTS.md` заголовок с v3.7.2 на v3.8.2~~ | ✅ v3.8.2 |
| 18 | ~~Обновить `skill/pipeline-orchestrator/SKILL.md` — v3.7.0 → v3.8.2, 16→17 агентов~~ | ✅ v3.8.2 |
| 19 | ~~Перестроить CRG граф (`code-review-graph build --force`)~~ | ✅ |
| 20 | ~~Обновить архитектурный HTML (`pipeline-architecture-detailed.html`)~~ | ✅ |
| 21 | ~~Обновить documenter.prompt — актуализировать промпт @documenter агента под v3.8.2~~ | ✅ |
| 22 | ~~Обновить README: direct→delegate для Flash-агентов, @quality в таблицу~~ | ✅ |
| 23 | ~~Обновить ARCHITECTURE.md: v3.8.2 заголовок, pipeline defs с @quality~~ | ✅ |

---

## Порядок работ

```
Этап 1 (быстрые фиксы) → pytest → Этап 2 (god functions) → pytest → 
Этап 3 (тесты) → pytest → Этап 4 (документация) → git push
```

**Риски:**
- scan_board (135 строк) — самый опасный рефакторинг, требует тестов ДО разбивки
- handle_run_agent (94 строки) — влияет на весь механизм делегации, осторожно
