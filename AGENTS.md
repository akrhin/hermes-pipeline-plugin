# AGENTS.md — Pipeline Plugin (v3.1, Kanban-native)

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

## Tools (v3.1)

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

### Полная таблица агентов и моделей

| Агент | Тип | Провайдер | Дефолтная модель | Когда вызывается |
|-------|-----|-----------|-----------------|------------------|
| @finder | Flash | `direct` | `deepseek-v4-flash` | Всегда первый — разведка, сбор информации |
| @analyst | Flash | `direct` | `deepseek-v4-flash` | Анализ, диагностика, поиск корня проблемы |
| @researcher | Free | `delegate_free` | `openrouter/free` | Внешние исследования (не используется в каждом пайплайне) |
| @architect | Pro | `delegate` | `deepseek-v4-pro` | Проектирование решения (требует рассуждений) |
| @planner | Flash | `direct` | `deepseek-v4-flash` | Разбивка на задачи |
| @coder | Flash | `direct` | `deepseek-v4-flash` | Написание кода |
| @editor | Flash | `direct` | `deepseek-v4-flash` | Редактирование (не всегда в пайплайне) |
| @fixer | Flash | `direct` | `deepseek-v4-flash` | Фикс известных багов |
| @refactorer | Flash | `direct` | `deepseek-v4-flash` | Рефакторинг |
| @reviewer | Pro | `delegate` | `deepseek-v4-pro` | Код-ревью с качественной оценкой |
| @security | Pro | `delegate` | `deepseek-v4-pro` | Security audit (только SECURITY_RELATED) |
| @integration | Pro | `delegate` | `deepseek-v4-pro` | Консистентность, кросс-файловые проверки |
| @tester | Flash | `direct` | `deepseek-v4-flash` | Написание тестов, прогон |
| @debugger | Flash | `direct` | `deepseek-v4-flash` | Отладка (только BUG_UNKNOWN) |
| @documenter | Flash | `direct` | `deepseek-v4-flash` | Документация |
| @devops | Flash | `direct` | `deepseek-v4-flash` | Инфраструктура (только INFRASTRUCTURE) |
| @optimizer | Flash | `direct` | `deepseek-v4-flash` | Оптимизация (только PERFORMANCE) |

### Как работают модели

Три режима выполнения:

- **`direct`** (Flash) — я выполняю задачу сам, в своём контексте. Не делегирую сабагенту. Дешево, быстро, подходит для механической работы.
- **`delegate`** (Pro) — я вызываю `delegate_task` с моделью `deepseek-v4-pro`. Дороже, но лучше для задач требующих рассуждений.
- **`delegate_free`** (Free) — то же делегирование, но через дешёвую модель (OpenRouter free). Для второстепенных задач.

### Настройка через `~/.hermes/plugins/pipeline/config.yaml`

Конфиг читается из собственного файла плагина (не из главного `config.yaml` Hermes).
Если файл отсутствует или секция `models` пуста — используются хардкодные значения из `BUILTIN_MODEL_MAP`.

```yaml
pipeline:
  models:
    # ── Defaults: применяются ко всем агентам данного типа ──
    defaults:
      direct:
        model: deepseek-v4-flash      # заменить Flash-модель для всех direct-агентов
      delegate:
        model: deepseek-v4-pro        # заменить Pro-модель для всех delegate-агентов
      delegate_free:
        model: openrouter/free        # заменить free-модель

    # ── Per-agent: точечное переопределение (высший приоритет) ──
    agents:
      # Можно переопределить только модель
      coder:
        model: deepseek-v4-pro
      # Можно переопределить провайдер и модель
      architect:
        provider: direct
        model: deepseek-v4-flash
      # Можно переопределить тип провайдера (меняется способ выполнения)
      tester:
        provider: delegate
        model: deepseek-v4-pro
      security:
        model: deepseek-v4-pro
```

#### Примеры конфигов

**A. Экономия токенов — все Pro в Flash:**
```yaml
pipeline:
  models:
    defaults:
      delegate:
        provider: direct
        model: deepseek-v4-flash
```
→ architect, reviewer, security, integration больше не делегируются, выполняются мной напрямую. Ноль вызовов `deepseek-v4-pro`.

**B. Только безопасность на Pro, всё остальное Flash:**
```yaml
pipeline:
  models:
    defaults:
      delegate:
        provider: direct
        model: deepseek-v4-flash
    agents:
      security:
        provider: delegate
        model: deepseek-v4-pro
```
→ все Pro-агенты стали Flash, кроме security (остался на Pro).

**C. Coder на самом мощном:**
```yaml
pipeline:
  models:
    agents:
      coder:
        provider: delegate
        model: openrouter/anthropic/claude-sonnet-4
```
→ @coder делегируется через OpenRouter с Claude Sonnet 4.

**D. Замена free-модели:**
```yaml
pipeline:
  models:
    defaults:
      delegate_free:
        model: perplexity/sonar-pro
```
→ researcher использует perplexity вместо OpenRouter free.

#### Приоритет слияния конфига

```
agents.<agent_id>        ← высший (точечная настройка конкретного агента)
defaults.<provider_type> ← средний (групповая настройка по типу)
BUILTIN_MODEL_MAP        ← низший (хардкод в models.py)
```

Если секция `pipeline.models` отсутствует или файл повреждён — используется хардкодная `BUILTIN_MODEL_MAP` из `models.py`. Никаких изменений в поведении.

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
| `plugin.yaml` | Manifest (v3.1.1, 12 tools) |
| `__init__.py` | Plugin core: 12 tools + register (MODEL_MAP из models.py) |
| `models.py` | **v2.2** Model config loader: YAML → merge → MODEL_MAP |
| `kanban.py` | Kanban API (create_tree, advance, converge, scan_board, resume) + ensemble (generate_candidates, judge_candidates, create_ensemble_subtasks) |
| `ensemble.py` | **NEW v3.0** Best-of-N ensemble core: generate_candidates (7 T-variations), judge_candidates (deterministic + LLM), should_use_ensemble, read_ensemble_config |
| `classify.py` | Keyword-based request classification |
| `agents/*.prompt` | Prompt templates for each agent + `judge.prompt` (LLM Judge) |
| `AGENTS.md` | This file (v3.1) |
| `ARCHITECTURE.md` | Full architecture doc (v2.1 — needs update) |
| `config.yaml` | Pipeline config (models + ensemble section) |
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

### v2.1 → v2.2

| Old | New |
|-----|-----|
| `MODEL_MAP` хардкод в `__init__.py` | `models.py` — загрузка из `~/.hermes/config.yaml → pipeline.models` |
| Менять модели = править код + рестарт | Менять модели = править `config.yaml` без изменения кода |
| 3 групповых типа (direct/delegate/free) | + per-agent override через `agents.<id>` |
| Один сценарий на все случаи | Гибкая настройка: defaults + per-agent, 4 примера конфигов |

## Pitfalls

- Плагин не содержит логики пайплайна — её несёт скилл-оркестратор
- После правки плагина нужен `hermes plugins reload` или рестарт сессии
- `kanban --json` парсится — если формат Hermes изменится, сломается
- `scan_board()` работает только с доской `pipeline`
- `--parent` в `create` не заполняет `parent_task_ids` в JSON, но `show` видит детей по `child_task_ids`
