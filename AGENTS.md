# AGENTS.md — Pipeline Plugin (v2.0, Kanban-native)

## What This Is

Плагин-оркестратор multi-agent пайплайнов для Hermes Agent.
**Variant C:** `state.json` удалён. `kanban.db` — единое состояние.
После рестарта: `pipeline_resume()` сканирует доску.

## Quick Start

```bash
ln -sf ~/git/hermes-pipeline-plugin ~/.hermes/plugins/pipeline
ln -sf ~/git/hermes-pipeline-plugin/skill/pipeline-orchestrator ~/.hermes/skills/hermes/pipeline-orchestrator
hermes plugins enable pipeline
```

## How It Works

Плагин регистрирует **10 инструментов**. Состояние — в kanban.board:
- Parent task «🔷 Пайплайн: ...» с дочерними тасками для каждого агента
- Статус агента: `ready` → `running` → `done`
- `promote` следующего агента при завершении предыдущего

## Tools (v2.1)

| Tool | Purpose |
|------|---------|
| `pipeline_classify(request)` | Classify → category + agent list |
| `pipeline_convergence(state, findings?)` | Evaluate convergence (deterministic) |
| `pipeline_save(state)` | Create/update kanban task tree (idempotent) |
| `pipeline_load()` | Reconstruct state from board → None if idle |
| `pipeline_resume()` | Scan board for active run → state or None |
| `pipeline_advance(state, agent)` | Mark agent done, promote next |
| `pipeline_clear()` | Close all tasks (cancel/abort) |
| `agent_prompt(agent_id, context)` | Build agent prompt from template |
| `agent_model(agent_id)` | Get provider + model for agent |
| `pipeline_run_agent(state, agent_id, context?)` | Build delegation package — returns prompt, model routing, and directive |

## Model Routing

Модели настраиваются через `~/.hermes/config.yaml` → секция `pipeline.models`.
Если секция отсутствует — используются значения по умолчанию (ниже).

- **По умолчанию:**
  - **Flash** (`direct`): Finder, Analyst, Planner, Coder, Editor, Fixer, Refactorer, Tester, Debugger, Documenter, DevOps, Optimizer
  - **Pro** (`delegate`): Architect, Reviewer, Security, Integration
  - **Free** (`delegate_free`): Researcher

- **Конфигурация** (опционально, `~/.hermes/config.yaml`):
  ```yaml
  pipeline:
    models:
      defaults:          # default overrides by provider type
        direct:
          model: deepseek-v4-flash
        delegate:
          model: deepseek-v4-pro
        delegate_free:
          model: openrouter/free
      agents:            # per-agent overrides (highest priority)
        coder:
          model: deepseek-v4-pro
  ```

## Delegation Package (via pipeline_run_agent)

`pipeline_run_agent()` возвращает delegation package с полем `directive`:

- **`directive: "delegate"`** → Pro (architect, reviewer, security, integration)
  Оркестратор вызывает `delegate_task(**call_args)` и получает результат.
- **`directive: "delegate_free"`** → Free-tier (researcher)
  Аналогично delegate, но через OpenRouter free модели.
- **`directive: "direct"`** → Flash (finder, analyst, planner, coder, editor, fixer,
  refactorer, tester, debugger, documenter, devops, optimizer)
  Оркестратор использует prompt напрямую в своём контексте.

**Правило:** никогда не вызывай `delegate_task` напрямую — всегда через `pipeline_run_agent`.
Порядок: `pipeline_run_agent(state, agent_id)` → прочитать `call_args` → `delegate_task(**call_args)` → `pipeline_advance(state, agent_id)`.

## Pipeline Agents

```
@finder → @analyst → @researcher → @architect → @planner → @coder
→ @reviewer → @security → @integration → @tester → @documenter
```

## Key Files

| File | Purpose |
|------|---------|
| `plugin.yaml` | Manifest (v2.1.0, 10 tools) |
| `__init__.py` | Plugin core: 10 tools + register |
| `models.py` | Model config loader: YAML → merge → MODEL_MAP |
| `kanban.py` | Kanban API (create_tree, advance, converge, scan_board, resume) |
| `classify.py` | Keyword-based request classification |
| `agents/*.prompt` | Prompt templates for each agent |
| `AGENTS.md` | This file |
| `ARCHITECTURE.md` | Full architecture doc |
| `skill/pipeline-orchestrator/` | Orchestrator skill |

## v1.x → v2.0 Changes

| Old | New (Variant C) |
|-----|----------------|
| `state.py` + `state.json` | **Removed.** Convergence logic in `kanban.py` |
| `pstate.save` → JSON file | `pipeline_save` → kanban task tree |
| `pstate.load` → read JSON | `pipeline_load` → scan_board() |
| Manual resume | `pipeline_resume()` — scans board |
| No advance tool | `pipeline_advance(state, agent)` |
| 7 tools | **9 tools** (+ resume + advance) |

### v2.0 → v2.1

| Old | New |
|-----|-----|
| 9 tools | **10 tools** (+ pipeline_run_agent) |
| Manual delegation routing in skill | Delegation package returned by plugin |
| Orchestrator guesses delegate vs direct | `directive` field tells orchestrator what to do |
| `agent_prompt` + `agent_model` call separately | `pipeline_run_agent` returns both + call_args |

## Pitfalls

- Плагин не содержит логики пайплайна — её несёт скилл-оркестратор
- После правки плагина нужен `hermes plugins reload` или рестарт сессии
- `kanban --json` парсится — если формат Hermes изменится, сломается
- `scan_board()` работает только с доской `pipeline`
- `--parent` в `create` не заполняет `parent_task_ids` в JSON, но `show` видит детей по `child_task_ids`
