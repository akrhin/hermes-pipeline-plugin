# AGENTS.md — Pipeline Plugin (v3.2.0, Kanban-native)

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

Плагин регистрирует **12 инструментов**. Состояние — в kanban.board:
- Parent task «🔷 Пайплайн: ...» с дочерними тасками для каждого агента
- Статус агента: `ready` → `running` → `done`
- `promote` следующего агента при завершении предыдущего

**v3.2.0 новые фичи:**
- **Retrospective logging** — структурированный JSONL-лог работы каждого handler'а
- **Hot-reload MODEL_MAP** — конфиг перечитывается по наносекундному mtime
- **Default prompt fallback** — для агентов без `.prompt` генерируется промпт из `AGENT_CONTEXT_FIELDS`
- **Convergence фильтрует status:fixed** — находит только открытые findings

## Tools (v3.2.0)

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
| `pipeline_ensemble_run(state, agent_id, n?)` | Generate N candidate packages for Best-of-N ensemble. Checks config (round ≤ max_round), creates kanban subtasks |
| `pipeline_ensemble_judge(request, candidates, judge_mode?)` | Evaluate N candidates and select best one. Modes: deterministic (MVP middle pick) or llm (generates judge prompt for delegation) |

## Model Routing

### Полная таблица агентов и моделей (v3.2.0)

| Агент | Тип | Провайдер | Дефолтная модель | Контекстные секции |
|-------|-----|-----------|-----------------|-------------------|
| @finder | Flash | `direct` | `deepseek-v4-flash` | research |
| @analyst | Flash | `direct` | `deepseek-v4-flash` | research |
| @researcher | Flash | `direct` | `deepseek-v4-flash` | research |
| @architect | Flash | `direct` | `deepseek-v4-flash` | research, planning |
| @planner | Flash | `direct` | `deepseek-v4-flash` | planning, infrastructure |
| @coder | Flash | `direct` | `deepseek-v4-flash` | implementation, planning |
| @fixer | Flash | `direct` | `deepseek-v4-flash` | implementation |
| @refactorer | Flash | `direct` | `deepseek-v4-flash` | implementation |
| @reviewer | Flash | `direct` | `deepseek-v4-flash` | implementation, research |
| @security | **Pro** | **`delegate`** | **`deepseek-v4-pro`** | implementation, research |
| @integration | Flash | `direct` | `deepseek-v4-flash` | implementation, documentation, infrastructure |
| @tester | Flash | `direct` | `deepseek-v4-flash` | implementation |
| @debugger | Flash | `direct` | `deepseek-v4-flash` | implementation |
| @documenter | Flash | `direct` | `deepseek-v4-flash` | implementation, documentation |
| @devops | Flash | `direct` | `deepseek-v4-flash` | infrastructure |
| @optimizer | Flash | `direct` | `deepseek-v4-flash` | implementation |

**Всего:** 16 агентов. Все Flash (`direct`), кроме security на Pro-делегации.

### Как работают модели

Два режима выполнения:

- **`direct`** (Flash) — я выполняю задачу сам, в своём контексте. Не делегирую сабагенту. Дешево, быстро, подходит для механической работы.
- **`delegate`** (Pro) — я вызываю `delegate_task` с моделью `deepseek-v4-pro`. Дороже, но лучше для audit безопасности.

Третий режим (`delegate_free`) определён в BUILTIN_MODEL_MAP для @researcher, но в текущем конфиге переопределён в direct.

### Настройка через конфиг

**`~/.hermes/plugins/pipeline/config.yaml`**

```yaml
pipeline:
  models:
    # ── Defaults: применяются ко всем агентам данного типа ──
    defaults:
      direct:
        model: deepseek-v4-flash
      delegate:
        provider: direct            # все Pro → Flash
        model: deepseek-v4-flash

    # ── Per-agent (высший приоритет) ──
    agents:
      security:
        provider: delegate
        model: deepseek-v4-pro
```

**Hot-reload:** конфиг перечитывается на каждый вызов. Не требует рестарта.

#### Приоритет слияния конфига

```
agents.<agent_id>        ← высший (точечная настройка конкретного агента)
defaults.<provider_type> ← средний (групповая настройка по типу)
BUILTIN_MODEL_MAP        ← низший (хардкод в models.py)
```

Если секция `pipeline.models` отсутствует или файл повреждён — используется только `BUILTIN_MODEL_MAP`.

## Agent .prompt файлы

Каждый агент имеет `.prompt` файл в `agents/`. Если файл отсутствует — генерируется default prompt из `AGENT_CONTEXT_FIELDS`.

Файлы с промптами: `architect`, `coder`, `integration`, `researcher`, `reviewer`, `security` и все 10 Flash-агентов (finder, analyst, planner, fixer, refactorer, tester, debugger, documenter, devops, optimizer).

## Delegation Package (via pipeline_run_agent)

`pipeline_run_agent()` возвращает delegation package с полем `directive`:

- **`directive: "delegate"`** → Pro (только security)
  Оркестратор вызывает `delegate_task(**call_args)` и получает результат.
- **`directive: "direct"`** → Flash (все остальные)
  Оркестратор использует prompt напрямую в своём контексте.

**Правило:** никогда не вызывай `delegate_task` напрямую — всегда через `pipeline_run_agent`.
Порядок: `pipeline_run_agent(state, agent_id)` → прочитать `call_args` → `delegate_task(**call_args)` → `pipeline_advance(state, agent_id)`.

## Pipeline Agents

```
@finder → @analyst → @researcher → @architect → @planner → @coder
→ @reviewer → @security → @integration → @tester → @documenter
```

(для SECURITY_RELATED — 11 агентов. Другие категории используют подмножество.)

## Retrospective (v3.2.0)

Пишется JSONL-лог в `~/.hermes/plugins/pipeline/retro/pipe_<id>.jsonl`.

События: pipeline_start, agent_start, agent_done, model_routing, convergence, findings, findings_detail, ensemble_gen, ensemble_judge, error, pipeline_clear, default_prompt.

Выключение:
```yaml
pipeline:
  retro:
    enabled: false
```

## Key Files

| File | Purpose |
|------|---------|
| `plugin.yaml` | Manifest (v3.2.0, 12 tools) |
| `__init__.py` | Plugin core: 12 tools + register + hot-reload MODEL_MAP + default prompt |
| `models.py` | v3.2.0 Model config loader: YAML → merge → MODEL_MAP |
| `kanban.py` | Kanban API (create_tree, advance, converge, scan_board, resume) + ensemble |
| `retro.py` | v3.2.0 Retrospective logging + auto-analysis |
| `ensemble.py` | Best-of-N ensemble: candidate generation + LLM/deterministic judge |
| `classify.py` | Request classification → 8 categories |
| `agents/*.prompt` | Prompt templates for 16 agents |
| `config.yaml` | Pipeline config: models, ensemble, retro |
