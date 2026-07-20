# Changelog

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
