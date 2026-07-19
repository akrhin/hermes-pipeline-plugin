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

Плагин регистрирует **9 инструментов**. Состояние — в kanban.board:
- Parent task «🔷 Пайплайн: ...» с дочерними тасками для каждого агента
- Статус агента: `ready` → `running` → `done`
- `promote` следующего агента при завершении предыдущего

## Tools (v2.0)

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

## Model Routing

- **Flash** (`direct`): Finder, Analyst, Planner, Coder, Editor, Fixer, Refactorer, Tester, Debugger, Documenter, DevOps, Optimizer
- **Pro** (`delegate_task`): Architect, Reviewer, Security, Integration
- **Free** (`delegate_free`, OpenRouter): Researcher, Commenter

## Pipeline Agents

```
@finder → @analyst → @researcher → @architect → @planner → @coder
→ @reviewer → @security → @integration → @tester → @documenter
```

## Key Files

| File | Purpose |
|------|---------|
| `plugin.yaml` | Manifest |
| `__init__.py` | Plugin core: 9 tools + register |
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

## Pitfalls

- Плагин не содержит логики пайплайна — её несёт скилл-оркестратор
- После правки плагина нужен `hermes plugins reload` или рестарт сессии
- `kanban--json` вывод парсится в `kanban.py` — если формат Hermes изменится, сломается
- `scan_board()` работает только с доской `pipeline`
