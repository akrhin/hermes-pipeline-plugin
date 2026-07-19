# Pipeline Plugin v2.1 — Architecture (Kanban-native)

## Purpose

Плагин-оркестратор для Hermes Agent, реализующий multi-agent пайплайны с quality gates.
**Variant C:** `state.json` удалён. `kanban.db` — единое состояние.
После рестарта: `pipeline_resume()` сканирует доску.

## Key Design Decisions

1. **Плагин, не MCP-сервер** — работает in-process с доступом к Hermes API и Kanban CLI.
2. **Нет команд** — пайплайн запускается по анализу сообщения агентом.
3. **Kanban.db = SSOT** — никакого `state.json`. Состояние живёт на доске `pipeline` в виде дерева задач.
4. **Три уровня моделей** — Flash (прямо), Pro (через delegation), OpenRouter free.
5. **Я — оркестратор** — плагин даёт инструменты, я шагаю по таскам на доске.

## Architecture

```
┌─ User ─────────────────────┐
│ "добавь JWT аутентификацию" │
└────────────┬────────────────┘
             ▼
┌─ Agent (я, DeepSeek V4 Flash) ───────────────────────┐
│                                                        │
│  1. Распознаю триггер → вызываю pipeline_classify()    │
│  2. Категоризирую → строю pipeline                     │
│  3. Создаю дерево задач на доске → pipeline_save()    │
│     ├─ Parent: «🔷 Пайплайн: ...»                     │
│     └─ Children: @finder, @analyst, ..., @documenter  │
│  4. Цикл по агентам:                                  │
│     ├─ pipeline_run_agent(state, agent) → pkg          │  ← NEW v2.1
│     ├─ delegate_task(**pkg.call_args)  (для Pro)       │
│     ├─ или выполняю prompt напрямую    (для Flash)      │
│     └─ pipeline_advance(state, agent) → promote next   │
│  5. Конвергенция: pipeline_convergence(state, findings)│
│     ├─ continue → @coder разблокирован на след. раунд  │
│     ├─ converged → parent complete                     │
│     ├─ stuck → parent blocked (needs_input)            │
│     └─ maxed_out → parent complete, escalation        │
│  6. pipeline_clear() → закрыть все таски              │
└────────────────────────────────────────────────────────┘
             │
             ▼
┌─ Pipeline Plugin (10 tools) ────────────────────────────┐
│                                                          │
│  pipeline_classify(request) → {category, pipeline[]}     │
│  pipeline_save(state)      → создаётдерево на доске     │
│  pipeline_load()           → scan_board()               │
│  pipeline_resume()         → scan_board() (resume)      │
│  pipeline_advance(s, a)    → mark done, promote next    │
│  pipeline_clear()          → close all tasks            │
│  pipeline_convergence(s,f) → evaluate + post to board   │
│  agent_prompt(id, ctx)     → build prompt from template │
│  agent_model(id)           → {provider, model}          │
│  pipeline_run_agent(s,a,c) → delegation package         │
│                                                          │
│  ┌─── classify.py ───────────────────┐                  │
│  │  keyword-based категоризация       │                  │
│  │  8 категорий + pipelines           │                  │
│  └────────────────────────────────────┘                  │
│  ┌─── kanban.py ──────────────────────┐                  │
│  │  create_task_tree                  │                  │
│  │  advance / evaluate_convergence    │                  │
│  │  on_convergence / on_clear         │                  │
│  │  scan_board / show_task / list     │                  │
│  └────────────────────────────────────┘                  │
│  ┌─── agents/ ────────────────────────┐                  │
│  │  architect.prompt / reviewer.prompt │                  │
│  │  security.prompt / researcher.prompt│                  │
│  │  integration.prompt                │                  │
│  └────────────────────────────────────┘                  │
└──────────────────────────────────────────────────────────┘
```

## Pipeline Definitions

| Category | Pipeline |
|----------|----------|
| FEATURE | finder → analyst → architect → planner → coder → reviewer → **integration** → tester → documenter |
| SECURITY_RELATED | finder → analyst → researcher → architect → planner → coder → reviewer → security → **integration** → tester → documenter |
| BUG_UNKNOWN | finder → debugger → fixer → reviewer → tester |
| BUG_KNOWN | finder → fixer → reviewer → tester |
| REFACTORING | finder → analyst → refactorer → reviewer → **integration** → tester |
| PERFORMANCE | finder → analyst → optimizer → reviewer → tester |
| INFRASTRUCTURE | finder → devops → (reviewer → tester if testable) |
| DOCUMENTATION | finder → documenter → (reviewer optional) |

## Kanban Task Tree

```
Parent: "🔷 Пайплайн: <request>"  [status: ready]
  ├── @finder: <request>          [status: ready → done]
  ├── @analyst: <request>         [status: todo → ready → done]
  ├── @researcher: <request>
  ├── @architect: <request>
  ├── @planner: <request>
  ├── @coder: <request>
  ├── @reviewer: <request>
  ├── @security: <request>
  ├── @integration: <request>
  ├── @tester: <request>
  └── @documenter: <request>      [status: todo]
```

Только один child в статусе `ready` в любой момент времени.
`pipeline_advance()` вызывает `promote` для следующего.
При конвергенции: findings → comment на parent. Converged → parent complete, все children close.

## Resume после restart

```python
state = pipeline_resume()  # scan_board()
if state:
    # Найден активный пайплайн:
    #   request, category, pipeline (11 agents),
    #   current_idx (кто ready), completed (кто done),
    #   kanban_parent_id, kanban_task_ids
    continue_pipeline(state)
else:
    # Доска пуста — работаем дальше
```

## Model Routing

| Agent | Executor | Model |
|-------|----------|-------|
| @finder, @analyst, @planner | Я напрямую | DeepSeek V4 Flash |
| @coder, @editor, @fixer, @refactorer | Я напрямую | DeepSeek V4 Flash |
| @tester, @debugger | Я напрямую | DeepSeek V4 Flash |
| @documenter, @devops, @optimizer | Я напрямую | DeepSeek V4 Flash |
| @architect | delegate_task | DeepSeek V4 Pro (delegation) |
| @reviewer | delegate_task | DeepSeek V4 Pro |
| @security | delegate_task | DeepSeek V4 Pro |
| @integration | delegate_task | DeepSeek V4 Pro |
| @researcher | delegate_task | OpenRouter free |

## Model Configuration (v2.2+)

MODEL_MAP больше не хардкодится в `__init__.py`. Вместо этого:

1. **`models.py`** содержит:
   - `BUILTIN_MODEL_MAP` — хардкодный fallback (текущие 17 агентов)
   - `load_model_config()` — читает `~/.hermes/config.yaml` → секция `pipeline.models`
   - Merge-логика: BUILTIN → defaults → agents

2. **`__init__.py`** вызывает `MODEL_MAP = load_model_config()` при импорте.

3. **Config merge priority:**
   1. `pipeline.models.agents.<agent_id>` — per-agent override (высший)
   2. `pipeline.models.defaults.<provider_type>` — default по типу провайдера
   3. `BUILTIN_MODEL_MAP` — хардкод (низший)

4. **Устойчивость:** если config.yaml отсутствует, битый, или секции нет —
   работает текущий хардкод без изменений.

## Convergence (deterministic, no LLM)

Алгоритм в `kanban.py` (бывший `state.py`):

1. **findings** = массив `{severity, file, category, description}`
2. **P0 + P1 = 0** → `converged`
3. **round >= max_rounds (3) и P0/P1 есть** → `maxed_out`
4. **Тот же fingerprint P0/P1 что в прошлом раунде** → `stuck`
5. **Иначе** → `continue`

## Files

```
hermes-pipeline-plugin/
├── ARCHITECTURE.md            ← этот файл (v2.2)
├── AGENTS.md                  ← инструкции для агентов (v2.2)
├── README.md
├── plugin.yaml                ← манифест v2.2.0
├── __init__.py                ← ядро: 10 хендлеров + регистрация (MODEL_MAP из models.py)
├── models.py                  ← NEW: MODEL_MAP loader (YAML config → merge)
├── classify.py                ← классификация (8 категорий)
├── kanban.py                  ← Kanban API: tree, advance, converge, scan, resume
├── LICENSE                    ← MIT
├── pyproject.toml             ← ruff config + build system
├── .github/workflows/test.yml ← CI (ruff + bandit + pytest)
├── agents/
│   ├── architect.prompt
│   ├── reviewer.prompt
│   ├── security.prompt
│   ├── integration.prompt
│   └── researcher.prompt
├── tests/
│   ├── test_classify.py           (21 тестов)
│   ├── test_init.py               (17 тестов)
│   ├── test_kanban_convergence.py (12 тестов)
│   └── test_models.py             ← NEW: тесты для load_model_config
├── skill/
│   └── pipeline-orchestrator/
│       ├── SKILL.md               ← оркестратор (checkpoints, revision loops)
│       ├── references/
│       │   ├── go-security-tools.md
│       │   └── pipeline_lessons.md
│       └── scripts/
│           └── go-quality-gates.sh
```

## Изменения (v1.x → v2.0)

| Дата | Что |
|------|-----|
| 2026-07-18 | Начальная архитектура (v1.0.0, 7 tools, state.json on disk) |
| 2026-07-18 | @integration agent, Kanban хуки (v1.2.0) |
| 2026-07-19 | **Variant C**: state.json → kanban.db SSOT, state.py → kanban.py, +pipeline_resume, +pipeline_advance, 9 tools (v2.0.0) |
| 2026-07-19 | **v2.1.0**: +pipeline_run_agent (delegation package pattern), 10 tools |
| 2026-07-19 | **v2.2.0**: MODEL_MAP → config.yaml (models.py) |
