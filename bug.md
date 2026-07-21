# BUG.md — Pipeline Plugin Defect Log

---

## [2026-07-21] Ошибка: CHANGELOG содержит ложные данные о количестве тестов

- **Файл:** CHANGELOG.md (строка 25)
- **Суть:** В changelog записано «Тесты — 4 879 passed, Ruff 0, Bandit 0, Compile OK». На самом деле в проекте **119 тестов** (6 файлов, никаких parametrize). Цифра 4 879 взята с прогона @quality на другом проекте, @documenter механически записал stdout в CHANGELOG.
- **Приоритет:** **High**

## [2026-07-21] Ошибка: classify.py — слишком длинные строки (E501)

- **Файл:** classify.py (строки 218, 262)
- **Суть:** Ruff находит 2 нарушения E501 (line > 100 chars): строка 218 (115 символов), строка 262 (101 символ). Не критично, но нарушает code style.
- **Приоритет:** Low

## [2026-07-21] Дефект: test_kanban_integration — 4 теста всегда skip

- **Файл:** tests/test_kanban_integration.py
- **Суть:** Функция `_has_kanban()` проверяет наличие board через `hermes kanban boards ls --json`. Плагин не использует Hermes Kanban CLI — он использует прямую SQLite в `~/.hermes/kanban/boards/pipeline/kanban.db`. Проверка всегда возвращает False, тесты (4 шт) всегда skip. Плагин может работать без Hermes core kanban CLI, и тесты должны проверять наличие БД напрямую.
- **Приоритет:** **High**

## [2026-07-21] Предупреждение: 14 функций > 50 строк

- **Суть:** CRG показывает 14 функций/методов длиннее 50 строк. Самые критичные:
  - `kanban.py::scan_board` — **134 строки** (L697-830)
  - `handlers/__init__.py::handle_run_agent` — **94 строки** (L375-468)
  - `test_retro_summary.py::test_full_pipeline_run` — **99 строк** (L289-387)
  - `retro.py::_build_metrics_sections` — **72 строки** (L388-459)
  - `__init__.py::register` — **73 строки** (L356-428)
- **Приоритет:** Mid

## [2026-07-21] Предупреждение: 9 неиспользуемых функций (dead code)

- **Файлы:** __init__.py, classify.py, ensemble.py, kanban.py, retro.py
- **Суть:** CRG нашёл 9 символов без единого caller/test reference:
  - `__init__.py::register` (сама register() — entry point, не ошибка)
  - `classify.py::priority`
  - `ensemble.py::generate_candidates` (дубль — в kanban.py тоже есть)
  - `kanban.py::unblock, list_tasks, get_agent_context, generate_candidates, judge_candidates`
  - `retro.py::context_selective`
- **Приоритет:** Low (dead code — не баг, а мусор)

## [2026-07-21] Замечание: plugin.yaml — pre_tool_call hook не реализован

- **Файл:** plugin.yaml (строка 18-19)
- **Суть:** В `provides_hooks` указан `pre_tool_call`, но в `__init__.py` нет соответствующей функции-хука. Проверка по Hermes SDK docs: hook должен быть зарегистрирован через `ctx.register_hook()`, чего нет.
- **Приоритет:** Mid

## [2026-07-21] Замечание: skills/ — pipeline-orchestrator ссылается на v3.6.0-3.7.0, но код на v3.8.2

- **Файл:** skill/pipeline-orchestrator/SKILL.md
- **Суть:** Описание скила указывает версию «v3.7.0», но код плагина уже v3.8.2. Есть расхождения: описано 16 агентов, а по факту 17 (добавлен @quality). Также в правиле «Правило 0» нет упоминания @quality gate для BUG_KNOWN/BUG_UNKNOWN/REFACTORING.
- **Приоритет:** Mid

## [2026-07-21] Замечание: Memory Setup документация не синхронизирована

- **Файл:** AGENTS.md и README.md
- **Суть:** В v3.8.2 были добавлены секции про Mnemosyne memory setup, но они не проверены на соответствие текущему коду. AGENTS.md говорит о `MEMORY.md`, которого нет в репозитории.
- **Приоритет:** Mid
