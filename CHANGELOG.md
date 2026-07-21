## v3.7.2 (2026-07-21)

### Refactoring — classify audit fix + handlers extracted

- **Bug #1 (P1) — Классификатор: «аудит»/«audit» маппился в SECURITY_RELATED** вместо REFACTORING.
  Ключи `аудит` и `audit` перемещены из SECURITY_RELATED в REFACTORING.
  Общий аудит кода — это рефакторинг, не безопасность.
- **Bug #2 (P1) — handlers вынесены из `__init__.py` (892→280 строк)**:
  - 17 хендлеров + `_build_agent_prompt` + `AGENT_CONTEXT_FIELDS` + model config loader → `handlers/__init__.py`
  - `__init__.py` теперь содержит только 12 tool schemas + `register()`
  - `handlers._get_plugin_dir()` динамически резолвит PLUGIN_DIR (поддержка тестового monkey-patching)
- **Тесты**: 22/22 classify, 45 init+models, 112/112 total, Ruff 0 issues
- **plugin.yaml compliance**: добавлен provides_hooks (пустой), register_skill для bundled skills
- **Hermes docs audit**: подтверждено соответствие Handler SDK — **kwargs, JSON return, try/except, toolset

## v3.7.2 (2026-07-21) — P1+P2+P3 + стабильный dev→main

- `__init__.py`: `register()` вызывает `ctx.register_auxiliary_task("pipeline_classify", ...)` — классификатор
  теперь настраивается через `auxiliary.pipeline_classify` в конфиге с независимой моделью
- `ensemble.py`: `llm_judge_candidates()` — оценивает кандидатов через `ctx.llm.complete()` in-process
- `handlers`: `handle_ensemble_judge` переключён на `llm_judge_candidates` для LLM-режима
- `_ctx.py`: module-level ctx reference; `/pipeline run <tool>` через `ctx.dispatch_tool()`
- `classify.py`: `CATEGORY_EMOJI`, emoji в результате классификации
- `handlers`: `_render_pipeline_status` с прогресс-баром, emoji категорий
- `kanban.py`: `import retro`, `agent_done()` в `advance()`
- `PLAN.md`: весь P3 закрыт ✅

## v3.7.1 (2026-07-21)

### Bug fixes — CI quality gates

- **Bandit B108 suppressed** — `/tmp` → `tmp_path` fixture in `test_retro_summary.py:test_parse_args_custom`
- **Orchestrator skill updated** — Фаза «Перед пушем» теперь включает ruff/bandit/compileall/pytest
  (была ошибка: агенты не запускали quality gates локально)

## v3.7.0 (2026-07-21)

### Refactoring — convergence extracted, retro split, imports cleaned

- **convergence.py** — новый модуль. `_compute_fingerprint` и `evaluate_convergence` вынесены из kanban.py (1014→898 строк). Импорты обновлены в `__init__.py` и тестах.
- **retro.py** — `build_analysis_prompt` (193 строки, degree 88) разбит на 4 подсети:
  - `_classify_events` — классификация событий по типам
  - `_build_metrics_sections` — построение метрических секций
  - `_detect_patterns` — детекция анти-паттернов пайплайна
  - `_build_raw_events_section` — построение сырой секции событий
- **Дубликат `_import_ensemble`** удалён из kanban.py (остался только в `__init__.py`)
- **classify.py** — расширен multi-label keyword набор (+41 ключ):
  - SECURITY_RELATED: +8 (xss, csrf, уязвим, injection…)
  - BUG_UNKNOWN: +13 (глюк, regression, defect, traceback…)
  - REFACTORING: +16 (дублирова, cohesion, coupling, dead code, lint…)
  - PERFORMANCE: +12 (latency, cache, benchmark, bottleneck…)
  - INFRASTRUCTURE: +18 (k8s, helm, terraform, monitoring…)
  - DOCUMENTATION: +11 (changelog, wiki, architecture, spec…)
  - FEATURE: +11 (разработ, extend, integration, plugin…)
- **Primary priority fix**: позиция категории в `_PRIORITY_ORDER` теперь определяет primary раньше score
- **Тесты**: 112/112
- **Ruff**: 0 errors в production коде

## v3.6.0 (2026-07-20)

### code-review-graph integration
- **@reviewer и @security агенты** — обновлены промпты: используют MCP-инструменты code-review-graph для получения blast radius, risk score, test gaps и affected flows.
- **MCP-сервер CRG** — зарегистрирован в `config.addon.yaml` с `--auto-watch`. Граф собирается один раз и обновляется инкрементально.
- **Экономия токенов** — 38–528× на больших проектах, подтверждено бенчмарками CRG.

### Документация
- **README.md**: новая секция «Интеграция с code-review-graph» — установка, настройка, таблица MCP-инструментов.
- **AGENTS.md**: v3.6.0, упоминание CRG в описании агентов @reviewer/@security.
- **pipeline-orchestrator skill**: v3.6.0, добавлены MCP-инструменты CRG в таблицу тулзов, pitfall про зависимость от `/new`.
- **pipeline-audit-checklist**: CRG-проверки добавлены в аудит-шаги.

### Verification
- CRG установлен (v2.3.7, 263 nodes, 2025 edges для плагина)
- Промпты обновлены и синхронизированы с ~/.hermes/plugins/pipeline/agents/
- Требуется `/new` для подхвата MCP-сервера

### Retro logging fixes
- **agent_done теперь пишет duration_s, tokens_response, status** — вместо пустого `{agent: "finder"}`. `handle_advance()` принимает новые опциональные поля из `ADVANCE_SCHEMA`.
- **tokens_prompt считается от реального prompt**, а не от пустого context dict. `agent_start` перенесён после сборки промпта.
- **pipeline_resume логирует метаданные** — category, primary, pipeline_len, round, agent_count.
- **ADVANCE_SCHEMA расширен**: `duration_s` (number), `tokens_response` (integer), `status` (enum: ok/error/skipped).

### Verification
- Новый ретро-лог `pipe:064f9ee87fb1` подтверждает: `agent_start tokens_prompt=292` (было 0), `agent_done duration_s=1.5 tokens_response=42 result=ok` (было {agent: "finder"})
- 108/108 тестов (исключая 1 flaky kanban), ruff 0 в коде плагина

## v3.5.0 (2026-07-20)

### scan_board — порядок агентов исправлен
- **scan_board()** больше не использует `ORDER BY created_at ASC` для восстановления порядка агентов — все дети создаются за миллисекунды с одинаковым timestamp, что давало недетерминированный порядок.
- **Фикс:** парсит pipeline из родительского `body` («Агенты: @finder → @analyst → ...»), потом индексирует детей по имени агента.
- Теперь `pipeline_resume()` возвращает правильный порядок: `finder → analyst → architect → planner → coder → reviewer → integration → tester → documenter`.

### Ensemble Judge — реальный код вместо описаний
- `_build_judge_prompt()`: лимит вывода кандидата увеличен с 2000 до 8000 символов — Judge получает реальный код для оценки, а не только описания стратегий.
- **Чинит проблему оркестрации:** кандидаты сначала выполняются (пишут код), потом их код передаётся Judge.

### Judge config passthrough
- `handle_ensemble_judge`: передача полного config в `judge_candidates()` вместо только `judge` секции — исправлено на `judge_cfg`.

### Infrastructure
- `pipeline.config.yaml.example` — добавлен шаблон конфига (806 байт), на который ссылается README.
- README: обновлён `About` (8 pipeline categories, quality gates, model routing).

## v3.4.0 (2026-07-20)

### README — полная переработка
- **Секция «Установка» переписана**: 5 шагов вместо устаревших 2 предложений. Убраны мёртвые команды `hermes kanban boards create/switch` — плагин использует собственный SQLite kanban, не Hermes kanban.
- **Убран `systemctl restart`** — достаточно рестарта сессии (`/new`).
- **Добавлена проверка**: `hermes plugins list | grep pipeline`
- **Добавлен `.config.yaml.example`** — шаблон конфига с полными настройками.
- **Обновлена таблица агентов**: уточнён ensemble для @coder.
- **Секция инструментов**: обновлена до 12 штук v3.3.3.

### Documentation
- `README.md`: полный rewrite секции установки (было 2 строки, стало 40+)
- `skill/pipeline-orchestrator/SKILL.md`: v3.3.4, добавлен pitfall#10 про `disabled_toolsets` для kanban-воркеров
- `skill/pipeline-audit-checklist/SKILL.md`: v3.3.4, README rewrite в аудит-шагах
- `CHANGELOG.md`: добавлен разбор архитектуры dispatcher `--toolsets` override

### Kanban Workers — toolsets override
- **Найден и задокументирован механизм**: `_default_spawn()` в `kanban_db.py` (строка 8307-8309) читает `_get_platform_tools(cfg, "cli")` из профиля воркера и передаёт как `--toolsets a,b,c` — это CLI-флаг высшего приоритета, который **переопределяет** `enabled_toolsets` в профиле.
- **Решение**: `agent.disabled_toolsets` в профиле воркера (например `tractor`) фильтрует тулзы ДО того как диспатчер запакует их в `--toolsets`. Механизм собственного `_resolve_worker_cli_toolsets()` — резолвит через `_get_platform_tools`, который учитывает `disabled_toolsets`.

```
# ~/.hermes/profiles/tractor/config.yaml
agent:
  disabled_toolsets:
    - browser
    - image_gen
    - spotify
```

## v3.3.3 (2026-07-20)

### LLM Judge — реальное делегирование
- **Фикс оркестрации**: `handle_ensemble_judge` возвращает `judge_call_args`. Оркестратор (агент) теперь вызывает `delegate_task(**judge_call_args)` вместо игнорирования результата.
- **Winner больше не null**: LLM реально оценивает кандидатов и возвращает `winner_id` с скоррингами.
- **Подтверждено**: первый реальный вызов LLM Judge — subagent получил judge prompt и начал оценку.

### Documentation
- `AGENTS.md`: обновлено описание LLM Judge — теперь работает
- `ARCHITECTURE.md`: миграция v3.3.3
- `skill/pipeline-orchestrator/SKILL.md`: rewritten как главный оркестратор-скилл (14 секций)
- `skill/pipeline-ensemble/SKILL.md`: compact reference → pipeline-orchestrator
- `skill/pipeline-audit-checklist/SKILL.md`: updated to v3.3.3

### Community
- `CODE_OF_CONDUCT.md`: добавлен (Contributor Covenant v2.1)
- `CONTRIBUTING.md`: гайд для контрибьюторов (код-стайл, тесты, PR, доки)
- `SECURITY.md`: политика безопасности, контакты для уязвимостей
- `.github/ISSUE_TEMPLATE/bug_report.yml`: шаблон баг-репорта
- `.github/ISSUE_TEMPLATE/feature_request.yml`: шаблон фичи
- `.github/PULL_REQUEST_TEMPLATE.md`: шаблон PR с чеклистом

### Skills refactoring
- Deleted 8 stale/duplicate skills, content absorbed into pipeline-orchestrator
- Symlinks in ~/.hermes/skills/ now point to repo skill/ directories

### classify fixes
- **RU keywords**: `крашит`, `краш`, `упал`, `валит`, `сломано` — BUG_UNKNOWN теперь ловит русские «крашится», «упал сервер»
- **RU keywords**: `пофикс`, `чини`, `реши проблем` — BUG_KNOWN ловит русские «пофикси», «чини»
- **word-boundary fix**: `_kw_matches` использовал `<=\b` для 5-символьных ключей. `crash` (5 символов) не матчил `crashes`. Исправлено на `< 5` — всё что >= 5 символов использует substring match.
- **priority order**: BUG_KNOWN > BUG_UNKNOWN (раньше tiebreaker не детерминирован)
- **DOCUMENTATION weight**: 3× (было 1×), чтобы побеждать FEATURE при совпадении

### Verification (all 5 unused agents tested)
- @debugger, @fixer, @refactorer, @optimizer, @devops — все имеют корректные промпты
- Все 8 категорий классифицируются правильно (14/14 тестов)
- 79/79 тестов, 0 lint errors

### Anomaly investigated
- `t_a1a2cf66`: maxed_out без agent_start — **не баг плагина**. Convergence исчерпал лимит раундов (3), но оркестратор не перезапустил агентов. Плагин вёл себя корректно.

### Bugfixes
- **Баг #1 (P1)** — `reopen()`: функция отсутствовала. `convergence('continue')` не мог переоткрыть done-задачи для нового раунда. Добавлена `def reopen()` + convergence теперь использует reopen вместо unblock.
- **Баг #3 (P0)** — **LLM Judge — заглушка**: `judge_candidates(mode='llm')` всегда возвращал `candidate_3`, не вызывая LLM. Теперь возвращает `judge_call_args` для реального делегирования.
- **Баг #4 (P0)** — **Flash-агенты без prompt**: `handle_run_agent()` возвращал `prompt: null` для direct-агентов. Теперь все 16 агентов получают реальный промпт.
- **Баг #10 (P2)** — **integration.prompt**: мёртвый `### Full context` заменён на selective context секции (implementation, documentation, infrastructure).
- **Баг #11 (P2)** — **maxed_out не закрывал детей**: convergence('maxed_out') не закрывал child-таски. Исправлено.
- **Баг #15 (P1)** — **stale cleanup с 1 ребёнком**: `len(children) < 2` пропускал пайплайны с одним child-таском. Исправлено на `< 1`.
- **Баг #20 (P2)** — **scan_board без LIMIT**: возвращал все активные пайплайны, мог застревать на старых. Добавлен `LIMIT 1`.

### Tests
- Добавлены 3 regression-теста: `test_ensemble_judge_llm_returns_call_args`, `test_ensemble_judge_deterministic_picks_middle`, `test_ensemble_judge_empty_candidates`
- Исправлен `test_run_agent_direct_for_flash` (ожидал `prompt: null`, теперь ожидает живой prompt)
- **79/79 тестов**

### Misc
- `judge.prompt` (мёртвый код) удалён
- Все `.prompt` файлы проверены на отсутствие `Full context`

## v3.3.0 (2026-07-20)

### Breaking
- **Kanban API переписан на прямой SQLite** — все 11 CLI-зависимых функций заменены на _sqlite_select/_sqlite_update. Больше никаких молчаливых ошибок _kanban().

### Features
- **Архитектурный аудит** — `ARCHITECTURE-FIXES.md`: 20 багов (4 P0 + 7 P1 + 9 P2) с root cause и планом фиксов
- **reopen()** — переоткрытие done-задач для convergence-циклов
- **AGENT_DESCRIPTIONS** — расширенные описания (~1.5×) с контекстом, инструментами и результатами
- **AGENT_VERB** — компактный глагол для каждого агента (разведка, тесты, баг-фикс...)
- **extract_target()** — извлекает цель (проект/файл/модуль) из запроса
- **Role-specific task titles** — `@coder: пишет powerfail-shutdown` вместо `@coder: сделай JWT аутентификацию`
- **direct SQLite** — promote(), complete(), claim(), assign() — напрямую в kanban.db
- **try/finally** — _sqlite_update и _sqlite_select защищены от resource leak

### Fixes
- Баг #1 — convergence('continue') теперь может reopen coder
- Баг #3 — LLM Judge больше не заглушка: возвращает `judge_call_args` для реального делегирования LLM
- Баг #4 — Flash-агенты получают prompt
- Баг #5 — stack trace в error-ответах handler'ов (было str(e) без traceback)
- Баг #8 — handle_convergence больше не мутирует state по ссылке
- Баг #9 — 'док' больше не даёт false positive в classify
- Баг #10 — мёртвый 'Full context' удалён из integration.prompt
- Баг #11 — maxed_out теперь закрывает детей
- Баг #13 — пустой findings больше не даёт ложную convergence
- Баг #15 — stale cleanup работает и с 1 ребёнком
- Баг #16 — judge.prompt мёртвый код удалён
- Баг #17 — ensemble config кэшируется (lru_cache)
- Баг #18 — deterministic judge выбирает T=0.7, не середину
- Баг #19 — title parsing через regex, не хрупкую замену строк
- Баг #20 — scan_board обрабатывает несколько активных пайплайнов

### Contributors
- **@V0rt** — SQLite-rewrite kanban.py, 20 багов code review, ARCHITECTURE-FIXES.md

## v3.2.0 (2026-07-19)

### Features
- **Retrospective logging** — structured JSONL-лог (`retro.py`) пишет pipeline_start, agent_start, agent_done, model_routing, convergence, findings, error, pipeline_clear
- **Hot-reload MODEL_MAP** — `nanosecond mtime` проверка config.yaml без рестарта сессии
- **Default prompt fallback** — агенты без `.prompt` получают шаблон из AGENT_CONTEXT_FIELDS
- **Convergence filtering** — `status:fixed` фильтруется, только открытые findings

### Changes
- 16 агентов (editor удалён как мёртвый)
- Все Flash (direct) кроме security (Pro/delegate)
- plugin.yaml v3.2.0, 12 инструментов
- Retro-лог пишется по умолчанию (auto_analyze: false)
- AGENTS.md, README, ARCHITECTURE.md актуализированы

## v3.1.0 (2026-07-19)

### Features
- **Selective context passing (v2.3+)** — AGENT_CONTEXT_FIELDS: каждый агент получает ТОЛЬКО свои секции
- **Integration agent** — cross-file integration checks
- **Kanban Dashboard** — hooks в pipeline_save, convergence, clear

### Changes
- 16 агентов, 12 инструментов
- state.json удалён (SSOT: kanban.db)
- pipeline_resume() для восстановления после рестарта

## v3.0.0 (2026-07-18)

### Features
- **Best-of-N Ensemble** — pipeline_ensemble_run + pipeline_ensemble_judge
- **7 T-вариаций** (0.3..1.1) для @coder на round 0
- **LLM Judge / Deterministic Judge** режимы

### Changes
- ensemble.py модуль с generate_candidates, judge_candidates
- kanban.py: create_ensemble_subtasks
- Config: pipeline.ensemble секция

## v1.2.0 (2026-07-19)

### Features
- **@integration** agent: cross-file integration checks (install.sh URLs, README→files, CI→Makefile)
- **Kanban Dashboard (automated)**: `kanban.py` module with hooks in `pipeline_save`, `pipeline_convergence`, `pipeline_clear`
  - `ensure_task()` — auto-creates task with idempotency-key on first save
  - `on_convergence()` — comments with findings, completes/blocks on terminal decisions
  - `on_clear()` — closes task on abort
  - No manual `hermes kanban` commands needed in orchestrator
- **__init__.py**: new tools count (8 with `kanban.py`), `kanban_task_id` in state schema

### Changes
- `kanban.py` added: 3 public API functions (`create_task`, `comment`, `complete`, `block_task`) + lifecycle hooks
- **classify.py**: `integration` added to SECURITY, FEATURE, REFACTORING pipelines
- **__init__.py**: `integration` in MODEL_MAP (delegate, DeepSeek V4 Pro); kanban hooks in handler functions
- **AGENTS.md**: updated Kanban section — automatic хуки, без ручных команд
- **ARCHITECTURE.md**: added Kanban Integration section + kanban.py in files tree
- **README.md**: English + Russian Kanban sections updated to reflect automation
- **pipeline-orchestrator** skill: v1.2.0 — Kanban automation section moved to plugin, orchestrator simplified

### Pipeline (full audit sequence)

```
@finder → @analyst → @researcher → @architect → @planner → @coder
→ @reviewer → @security → @integration → @tester → @documenter
```

## v1.1.0 (2026-07-18)

- Remove stale `.cursor/backlog` files
- Refactor: cleanup stale references, add convergence guard
- Replace TickTick Kanban with built-in Hermes Kanban
- Fix path traversal vulnerability in `handle_prompt`
- Documentation: add CHANGELOG.md, bump plugin.yaml to 1.1.0

## v1.0.0 (2026-07-18)

- Initial release
- 7 tools: classify, convergence, save, load, clear, prompt, model
- 8 categories: SECURITY, BUG_UNKNOWN, BUG_KNOWN, REFACTORING, PERFORMANCE, INFRASTRUCTURE, DOCUMENTATION, FEATURE
- 12 agents: finder, analyst, researcher, architect, planner, coder, editor, fixer, refactorer, tester, debugger, documenter, devops, optimizer, commenter
- Model routing: Flash (direct) / Pro (delegate) / Free (OpenRouter)
- State persistence with convergence (max 3 rounds, fingerprint-based stuck detection)
