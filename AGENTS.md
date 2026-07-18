# AGENTS.md — Pipeline Plugin

## What This Is

Плагин-оркестратор multi-agent пайплайнов для Hermes Agent.
Не MCP-сервер.

## Quick Start

```bash
# 1. установка плагина
ln -sf ~/git/hermes-pipeline-plugin ~/.hermes/plugins/pipeline
hermes plugins enable pipeline

# 2. установка скила-оркестратора (обязательно!)
ln -sf ~/git/hermes-pipeline-plugin/skill/pipeline-orchestrator ~/.hermes/skills/hermes/pipeline-orchestrator

# 3. проверка
hermes plugins list | grep pipeline
```

## How It Works

Плагин регистрирует 7 инструментов. Агент (я) вызывает их по ходу пайплайна:

1. `pipeline_classify(request)` — категоризировать запрос
2. `pipeline_convergence(findings)` — оценить конвергенцию (детерминированно)
3. `pipeline_save(state)` — сохранить прогресс
4. `pipeline_load()` — загрузить прогресс
5. `pipeline_clear()` — сбросить пайплайн
6. `agent_prompt(agent_id, context)` — сгенерировать промпт агента
7. `agent_model(agent_id)` — получить модель для агента

## Model Routing

- Flash → делает агент напрямую (Finder, Analyst, Planner, Coder, Editor, Fixer, Refactorer, Tester, Debugger, Documenter, DevOps, Optimizer)
- Pro → delegate_task (Architect, Reviewer, Security, **Integration**)
- Free → delegate_task с OpenRouter free (Researcher, Commenter)

## Pipeline Agents (v1.2.0)

Полная последовательность для полного аудита:

```
@finder → @analyst → @researcher → @architect → @planner → @coder
→ @reviewer → @security → @integration → @tester → @documenter
```

`@integration` (новый, v1.2.0) проверяет кросс-файловые точки:
- install.sh → release assets
- README → существующие файлы
- CI → Makefile (цели существуют)
- Документация → реальные инструменты

## Kanban Dashboard (автоматическая)

Начиная с v1.2.0, пайплайн **автоматически** ведёт доску `pipeline` через модуль `kanban.py`:

| Событие | Действие на доске |
|---------|-------------------|
| Старт пайплайна | `hermes kanban create` с idempotency-key |
| Каждый раунд конвергенции | `hermes kanban comment` с findings |
| Converged | `hermes kanban complete` с metadata |
| Stuck | `hermes kanban block` (needs human) |
| Maxed out | `hermes kanban complete` |
| Очистка | `hermes kanban complete` (Cancelled) |

Никаких ручных команд — хуки в `pipeline_save`, `pipeline_convergence`, `pipeline_clear` всё делают сами.

## Key Files

| File | Purpose |
|------|---------|
| `plugin.yaml` | Manifest |
| `__init__.py` | Plugin core: register + tool handlers |
| `classify.py` | Keyword-based request classification |
| `state.py` | JSON state persistence on disk |
| `agents/*.prompt` | Prompt templates for each delegate agent |
| `ARCHITECTURE.md` | Full architecture doc |
| `skill/pipeline-orchestrator/` | Orchestrator skill (instructions for the agent) |

## Related

- Hermes Agent plugin docs: https://hermes-agent.nousresearch.com/docs
- Hermes plugins dir: `~/.hermes/plugins/`

## Common Pitfalls

- Плагин не содержит логики пайплайна — не пытайся запихнуть её туда
- Промпты в `agents/*.prompt` не Python-файлы, а текстовые шаблоны с `{placeholders}`
- `state.json` живёт в директории плагина, не в конфиге Hermes
- После правки плагина нужен рестарт сессии или `hermes plugins reload`
