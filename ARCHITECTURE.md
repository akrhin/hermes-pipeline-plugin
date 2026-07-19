# Pipeline Plugin v3.1 — Architecture (Kanban-native + Ensemble)

## Purpose

Плагин-оркестратор для Hermes Agent, реализующий multi-agent пайплайны с quality gates.
**Variant C:** `state.json` удалён. `kanban.db` — единое состояние.
После рестарта: `pipeline_resume()` сканирует доску.

## Key Design Decisions

1. **Плагин, не MCP-сервер** — работает in-process с доступом к Hermes API и Kanban CLI.
2. **Нет команд** — пайплайн запускается по анализу сообщения агентом.
3. **Kanban.db = SSOT** — никакого `state.json`. Состояние живёт на доске `pipeline` в виде дерева задач.
4. **Три уровня моделей** — Flash (напрямую), Pro (через delegation), OpenRouter free.
5. **Я — оркестратор** — плагин даёт инструменты, я шагаю по таскам на доске.
6. **Selective context** — каждый агент получает только те секции контекста, которые ему нужны (AGENT_CONTEXT_FIELDS).
7. **Best-of-N Ensemble** — для @coder N=5 независимых генераций с разной temperature, judge выбирает лучшее.

## Architecture

```
┌─ User ─────────────────────────────────────────────────┐
│ "добавь JWT аутентификацию"                             │
└────────────┬────────────────────────────────────────────┘
             ▼
┌─ Agent (я, DeepSeek V4 Flash) ───────────────────────────────────────────┐
│                                                                           │
│  1. Распознаю триггер → вызываю pipeline_classify()                      │
│  2. Категоризирую → строю pipeline                                       │
│  3. Создаю дерево задач на доске → pipeline_save()                       │
│     ├─ Parent: «🔷 Пайплайн: ...»                                       │
│     └─ Children: @finder, @analyst, ..., @documenter                     │
│  4. Цикл по агентам с selective context:                                 │
│     ├─ pipeline_run_agent(state, agent) → pkg (Pro) или prompt (Flash)   │
│     ├─ Если @coder и round=0 и ensemble enabled:                         │
│     │   ├─ pipeline_ensemble_run → 5 candidates (T=0.3..1.1)            │
│     │   ├─ delegate_task × 5 (параллельно, через orchestrator)          │
│     │   └─ pipeline_ensemble_judge → winner                             │
│     ├─ delegate_task(**pkg.call_args) (для Pro / ensemble)              │
│     └─ pipeline_advance(state, agent) → promote next                    │
│  5. Конвергенция: pipeline_convergence(state, findings)                  │
│     ├─ continue → @coder разблокирован (single pass, ensemble OFF)      │
│     ├─ converged → parent complete                                      │
│     ├─ stuck → parent blocked (needs_input)                             │
│     └─ maxed_out → parent complete, escalation                          │
│  6. pipeline_clear() → закрыть все таски                                │
└──────────────────────────────────────────────────────────────────────────┘
             │
             ▼
┌─ Pipeline Plugin (12 tools) ──────────────────────────────────────────────────┐
│                                                                               │
│  pipeline_classify(request)              → {category, pipeline[]}             │
│  pipeline_save(state)                    → создаёт дерево на доске            │
│  pipeline_load()                         → scan_board()                      │
│  pipeline_resume()                       → scan_board() (resume)             │
│  pipeline_advance(s, a)                  → mark done, promote next           │
│  pipeline_clear()                        → close all tasks                   │
│  pipeline_convergence(s, f)              → evaluate + post to board          │
│  agent_prompt(id, ctx)                  → build prompt from template        │
│  agent_model(id)                         → {provider, model}                 │
│  pipeline_run_agent(s, a, c)             → delegation package                │
│  pipeline_ensemble_run(s, a, n?)         → N candidate packages (ensemble)  │  ← NEW v3.0
│  pipeline_ensemble_judge(req, cands, m?) → select best candidate            │  ← NEW v3.0
│                                                                               │
│  ┌─── classify.py ───────────────────────┐                                   │
│  │  keyword-based категоризация           │                                   │
│  │  8 категорий + pipelines               │                                   │
│  └────────────────────────────────────────┘                                   │
│  ┌─── kanban.py ──────────────────────────┐                                   │
│  │  create_task_tree                      │                                   │
│  │  advance / evaluate_convergence        │                                   │
│  │  on_convergence / on_clear             │                                   │
│  │  scan_board / show_task / list         │                                   │
│  │  create_ensemble_subtasks              │  ← NEW: N подтасков под ensemble  │
│  └────────────────────────────────────────┘                                   │
│  ┌─── ensemble.py ────────────────────────┐                                   │
│  │  generate_candidates() — 7 T-variations │  ← NEW v3.0                      │
│  │  judge_candidates() — det + LLM        │                                   │
│  │  should_use_ensemble() — config-driven │                                   │
│  │  read_ensemble_config()                │                                   │
│  └────────────────────────────────────────┘                                   │
│  ┌─── agents/ ────────────────────────────┐                                   │
│  │  architect.prompt / reviewer.prompt     │                                   │
│  │  security.prompt / researcher.prompt    │                                   │
│  │  integration.prompt / judge.prompt      │                                   │
│  └────────────────────────────────────────┘                                   │
└───────────────────────────────────────────────────────────────────────────────┘
```

## Pipeline Definitions

| Category | Pipeline |
|----------|----------|
| FEATURE | finder → analyst → architect → planner → coder* → reviewer → integration → tester → documenter |
| SECURITY_RELATED | finder → analyst → researcher → architect → planner → coder* → reviewer → security → integration → tester → documenter |
| BUG_UNKNOWN | finder → debugger → fixer → reviewer → tester |
| BUG_KNOWN | finder → fixer → reviewer → tester |
| REFACTORING | finder → analyst → refactorer → reviewer → integration → tester |
| PERFORMANCE | finder → analyst → optimizer → reviewer → tester |
| INFRASTRUCTURE | finder → devops → (reviewer → tester if testable) |
| DOCUMENTATION | finder → documenter → (reviewer optional) |

> * `@coder` заменяется на `@coder-ensemble` если ensemble включён (см. config.yaml pipeline.ensemble)

## Kanban Task Tree

```
Parent: "🔷 Пайплайн: <request>"  [status: ready → running → done]
  ├── @finder: <request>          [status: ready → done]
  ├── @analyst: <request>
  ├── @planner: <request>
  ├── @coder (ensemble):          [status: running]
  │   ├── candidate_1             [subtask, T=0.3]
  │   ├── candidate_2             [subtask, T=0.5]
  │   ├── candidate_3             [subtask, T=0.7]
  │   ├── candidate_4             [subtask, T=0.9]
  │   ├── candidate_5             [subtask, T=1.1]
  │   └── @judge                  [subtask, after all candidates done]
  ├── @reviewer: <request>
  ├── @integration: <request>
  ├── @tester: <request>
  └── @documenter: <request>
```

## Selective Context (AGENT_CONTEXT_FIELDS)

Каждый агент получает только нужные секции контекста вместо полного дампа:

| Agent | Gets | Skipped |
|-------|------|---------|
| @finder | research | planning, implementation, quality, docs, infra |
| @analyst | research | planning, implementation, quality, docs, infra |
| @architect | research, planning | implementation, quality, docs, infra |
| @planner | planning, infrastructure | research, implementation, quality |
| @coder | implementation, planning | research, quality, docs, infra |
| @reviewer | implementation, research | planning, quality, docs, infra |
| @security | implementation, research | planning, quality, docs, infra |
| @integration | implementation, documentation, infrastructure | research, planning, quality |
| @tester | implementation | research, planning, quality, docs, infra |
| @documenter | implementation, documentation | research, planning, quality, infra |

## Best-of-N Ensemble Flow

```
if round == 0 and agent == 'coder' and ensemble enabled (config.yaml):
  1. pipeline_ensemble_run(state, 'coder', n=5)
     → generate_candidates(): 7 вариаций T=0.3..1.1
     → create_ensemble_subtasks(): N подтасков на доске
     → возвращает [{id, task, temperature, instruction_extra}, ...]

  2. orchestrator: delegate_task × N (параллельно)
     → каждый candidate выполняется независимо
     → кандидаты НЕ знают друг о друге

  3. pipeline_ensemble_judge(request, candidates, judge_mode)
     → deterministic (MVP): средний кандидат
     → llm: build_judge_prompt() → делегация в LLM Judge
     → возвращает {winner_id, rationale, scores}

  4. winner → @reviewer (как обычный код)

else (round > 1 или ensemble disabled):
  → single pass @coder (экономия)
```

### Cost optimization

- На round 0: ensemble N=5 (5× cost, ~0.77 руб)
- На round 1+: ensemble auto-off (disable_on_round_gt: 1)
- Single pass @coder: ~0.12 руб
- Точка безубыточности: если ensemble экономит >1 convergence round

## Convergence Engine

Детерминированная конвергенция (без LLM):

```
evaluate_convergence(state, findings):
  1. Если findings заданы — вычисляет fingerprint, запоминает prev
  2. Если нет P0/P1 findings → converged
  3. Если round >= max_rounds → maxed_out
  4. Если fingerprint не изменился → stuck
  5. Иначе → continue (разблокировать @coder на след. раунд)
```

## Configuration (config.yaml)

```yaml
pipeline:
  models:
    # model config для каждого агента
    defaults:
      delegate:
        model: deepseek-v4-flash
    agents:
      coder:
        provider: delegate
        model: deepseek-v4-flash

  ensemble:
    enabled: true
    default_n: 5
    max_n: 10
    agents:
      coder:
        enabled: true
        n: 5
        judge_mode: llm
    judge:
      model: deepseek-v4-flash
      provider: polza
    cost_optimization:
      disable_on_round_gt: 1
```

Конфиг читается из `~/.hermes/plugins/pipeline/config.yaml`. При отсутствии — fallback на BUILTIN_MODEL_MAP. Ensemble секция при отсутствии — fallback на DEFAULT_ENSEMBLE_CONFIG.

## Key Files

| File | Purpose |
|------|---------|
| `plugin.yaml` | Manifest (v3.1.1, 12 tools) |
| `__init__.py` | Plugin core: 12 tools + register + AGENT_CONTEXT_FIELDS |
| `models.py` | v2.2 Model config loader: YAML → merge → MODEL_MAP |
| `kanban.py` | Kanban API (create_tree, advance, converge, scan_board, resume) + create_ensemble_subtasks |
| `ensemble.py` | **NEW v3.0** Best-of-N core: generate_candidates (7 T-variations), judge_candidates (det + LLM), should_use_ensemble, read_ensemble_config |
| `classify.py` | Keyword-based request classification (8 categories) |
| `agents/*.prompt` | Prompt templates for each agent + judge.prompt (LLM Judge) |
| `config.yaml` | Pipeline config (models + ensemble section) |
| `AGENTS.md` | This file (v3.1, agent documentation) |
| `skill/pipeline-orchestrator/` | Orchestrator skill |

## Migration History

| Version | Changes |
|---------|---------|
| v1.0 | Basic pipeline with state.json |
| v1.2 | Kanban integration |
| v2.0 | Variant C: state.json → kanban.db SSOT. unblock → promote alias. 9 tools |
| v2.1 | pipeline_run_agent — 10th tool. Delegation package pattern |
| v2.2 | config.yaml вынос MODEL_MAP. models.py merge logic |
| v2.3 | **Selective context** (AGENT_CONTEXT_FIELDS). full_context удалён |
| v3.0 | **Best-of-N skeleton**: pipeline_ensemble_run, pipeline_ensemble_judge, judge.prompt |
| v3.1 | **Ensemble production**: ensemble.py, config-driven, LLM Judge, kanban subtasks |
