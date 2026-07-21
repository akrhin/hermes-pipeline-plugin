# Pipeline Plugin — Баги

## Активные

| # | Severity | Описание | Файл | Статус |
|---|----------|----------|------|--------|
| 1 | P2 | В execute_code() нельзя передавать сложные shell-команды через f-строки с вложенными кавычками — SyntaxError. Решение: писать скрипт на диск (write_file) и запускать terminal("python3 /tmp/script.py") | execute_code / terminal | ⚠️ |
| 2 | High | test_kanban_integration — 4 теста всегда skip (_has_kanban() проверяет Hermes CLI, а не прямую SQLite) | tests/test_kanban_integration.py | ⚠️ |
| 3 | Mid | 14 функций > 50 строк (самые критичные: scan_board 134, handle_run_agent 94) | kanban.py, handlers/__init__.py | ⚠️ |
| 4 | Low | 2 E501 (line > 100) в classify.py (строки 218, 262) | classify.py | ⚠️ |
| 5 | Mid | plugin.yaml — pre_tool_call hook не реализован | plugin.yaml | ⚠️ |

## Пофикшенные в v3.8.x

| # | Версия | Баг | Статус |
|---|--------|-----|--------|
| 1 | v3.8.2 | Dead code в kanban.py удалён — `generate_candidates`, `judge_candidates` (дубли из `ensemble.py`). 97 строк unreachable, 10× F821 | ✅ |
| 2 | v3.8.2 | Модели fix — все Flash-агенты переключены на `delegate/polza/deepseek-v4-flash`. 5 тестов починены (проверка контракта вместо жёстких значений) | ✅ |
| 3 | v3.8.1 | Quality gates не запускались до пуша — @quality агент | ✅ |
| 4 | v3.8.1 | Потеря контекста после рестарта — persona permanent auto-resume | ✅ |
| 5 | v3.8.1 | Форматирование — конфликт skills, синхронизированы | ✅ |
| 6 | v3.8.1 | CI упал с ruff F401 в handlers/__init__.py — dead import json | ✅ |
|| 7 | v3.8.2 | CHANGELOG.md — ложные данные о 4 879 тестах (реально 119) | ✅ |
|| 8 | v3.8.2 | Documenter docs update — README, ARCHITECTURE, BUG, PLAN синхронизированы с v3.8.2 | ✅ |
|| 9 | v3.8.2 | threading.local() → модульная переменная _KANBAN_CONN + проверка живости SELECT 1 | ✅ |
|| 10 | v3.8.2 | call_args = {'goal': prompt} — упрощение контракта (fix #2) | ✅ |
|| 11 | v3.8.2 | @quality не было в AGENT_CONTEXT_FIELDS (P1) | ✅ |
|| 12 | v3.8.2 | _close_connection() не вызывался в on_clear() (P1) | ✅ |
|| 13 | v3.8.2 | DEFAULT_RETRO_CONFIG auto_analyze: False → True (P1) | ✅ |
|| 14 | v3.8.2 | Unused params: promote(force), complete(metadata), block_task(reason) (P2) | ✅ |
|| 15 | v3.8.2 | Unused param run_context в build_analysis_prompt() (P2) | ✅ |
|| 16 | v3.8.2 | Unused param config в build_judge_call_args() (P2) | ✅ |
|| 17 | v3.8.2 | threading.Lock() для _KANBAN_CONN + _MODEL_MAP_CACHE (P2) | ✅ |
|| 18 | v3.8.2 | Dead code path в _import_ensemble() починен (P2) | ✅ |

## Задокументировано в ARCHITECTURE-FIXES.md

Все 20 багов (4 P0 + 7 P1 + 9 P2) пофикшены к v3.3.1.
См. [ARCHITECTURE-FIXES.md](./ARCHITECTURE-FIXES.md).
