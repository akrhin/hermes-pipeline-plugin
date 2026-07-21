# AGENTS.md — Pipeline Plugin (v3.7.2, SQLite-native + handlers/)

## What This Is

Плагин-оркестратор multi-agent пайплайнов для Hermes Agent.
**Variant C:** `state.json` удалён. `kanban.db` — единое состояние.
**v3.7.2:** 17 хендлеров вынесены из `__init__.py` (892→280 строк) в `handlers/__init__.py`.

### v3.7.2 — handlers/extraction

- **17 хендлеров** вынесены из `__init__.py` (892→280 строк) в `handlers/__init__.py`
- `__init__.py` содержит только 12 tool schemas + `register()`
- Классификатор: «аудит»/«audit» → REFACTORING (было SECURITY_RELATED)

### v3.7.2 — plugin compliance

- **plugin.yaml**: добавлен `provides_hooks` (пустой, для соответствия SDK)
- **register()**: добавлена `ctx.register_skill()` для bundled skills (`pipeline-orchestrator`, `pipeline-ensemble`, `pipeline-audit-checklist`)
- **Аудит по официальной Hermes plugin development docs**: подтверждено — все handler signatures с `**kwargs`, JSON return, try/except, toolset='pipeline'

**v3.6.0:** интеграция с **code-review-graph (CRG)** — локальный граф кода на Tree-sitter. @reviewer и @security используют MCP-инструменты CRG.

## Quick Start

```bash
ln -sf ~/git/hermes-pipeline-plugin ~/.hermes/plugins/pipeline
ln -sf ~/git/hermes-pipeline-plugin/skill/pipeline-orchestrator ~/.hermes/skills/hermes/pipeline-orchestrator
hermes plugins enable pipeline
```

## How It Works

Плагин регистрирует **12 инструментов**. Состояние — в `kanban.board` (прямой SQLite, без CLI):

- Parent task «🔷 Пайплайн: ...» с дочерними тасками для каждого агента
- Статус агента: `ready` → `running` → `done`
- `promote` следующего агента при завершении предыдущего

**v3.3.0 новые фичи:**
- **SQLite Kanban** — все 11 функций Kanban API напрямую через sqlite3, без `hermes kanban` CLI. Никаких молчаливых ошибок.
- **20 багов пофикшено** — см. `ARCHITECTURE-FIXES.md` (4 P0 + 7 P1 + 9 P2)
- **reopen()** — переоткрытие done-задач для convergence-циклов
- **AGENT_VERB + _extract_target()** — компактные заголовки задач вида `@coder: пишет powerfail-shutdown`
- **retro-логи** — JSONL-лог каждого прогона
- **Hot-reload MODEL_MAP** — конфиг перечитывается по наносекундному mtime
- **Default prompt fallback** — для агентов без `.prompt` генерируется промпт из `AGENT_CONTEXT_FIELDS`
- **Convergence фильтрует status:fixed** — находит только открытые findings

## Tools (v3.3.0)

| Tool | Purpose |
|------|---------|
| `pipeline_classify(request)` | Classify → category + agent list |
| `pipeline_convergence(state, findings?)` | Evaluate convergence (deterministic) |
| `pipeline_save(state)` | Create/update kanban task tree (idempotent) — прямой INSERT в SQLite |
| `pipeline_load()` | Reconstruct state from board → None if idle |
| `pipeline_resume()` | Scan board for active run → state or None |
| `pipeline_advance(state, agent)` | Mark agent done, promote next |
| `pipeline_clear()` | Close all tasks (cancel/abort) |
| `agent_prompt(agent_id, context)` | Build agent prompt from template |
| `agent_model(agent_id)` | Get provider + model for agent |
| `pipeline_run_agent(state, agent_id, context?)` | Build delegation package — returns prompt, model routing, and directive |
| `pipeline_ensemble_run(state, agent_id, n?)` | Generate N candidate packages for Best-of-N ensemble |
| `pipeline_ensemble_judge(request, candidates, judge_mode?)` | Evaluate N candidates and select best one |

## Model Routing

### Полная таблица агентов и моделей (v3.3.0)

| Агент | Тип | Провайдер | Дефолтная модель | Контекстные секции | Описание |
|-------|-----|-----------|-----------------|-------------------|----------|
| @finder | Flash | `direct` | `deepseek-v4-flash` | research | Сбор информации: чтение кода, файлов и конфигов, разведка перед анализом |
| @analyst | Flash | `direct` | `deepseek-v4-flash` | research | Анализ и диагностика: поиск корня проблемы, разбор логов, выявление закономерностей |
| @researcher | Flash | `direct` | `deepseek-v4-flash` | research | Внешние исследования: best practices, документация, альтернативы |
| @architect | Flash | `direct` | `deepseek-v4-flash` | research, planning | Проектирование: архитектура изменений, выбор компонентов, связи модулей |
| @planner | Flash | `direct` | `deepseek-v4-flash` | planning, infrastructure | Планирование: разбивка на подзадачи, оценка объёма, план шагов |
| @coder | Flash | `direct` | `deepseek-v4-flash` | implementation, planning | Разработка: написание кода, реализация фич, имплементация логики |
| @fixer | Flash | `direct` | `deepseek-v4-flash` | implementation | Исправление: патчи багов, замена сломанных вызовов, обходы проблем |
| @refactorer | Flash | `direct` | `deepseek-v4-flash` | implementation | Рефакторинг: улучшение структуры, устранение дублирования, выделение функций |
| @reviewer | Flash | `direct` | `deepseek-v4-flash` | implementation, research | Код-ревью: проверка качества, логические ошибки, рекомендации |
| @security | **Pro** | **`delegate`** | **`deepseek-v4-pro`** | implementation, research | Аудит безопасности: XSS, SQL-инъекции, утечки данных, права доступа |
| @integration | Flash | `direct` | `deepseek-v4-flash` | implementation, documentation, infrastructure | Консистентность: кросс-файловые связи, импорты, типы, совместимость API |
| @tester | Flash | `direct` | `deepseek-v4-flash` | implementation | Тестирование: написание тестов, прогон, регрессия, assertions |
| @debugger | Flash | `direct` | `deepseek-v4-flash` | implementation | Отладка: пошаговый поиск первопричины, стек, анализ переменных |
| @documenter | Flash | `direct` | `deepseek-v4-flash` | implementation, documentation | Документация: README, AGENTS.md, changelog, комментарии, инструкции |
| @devops | Flash | `direct` | `deepseek-v4-flash` | infrastructure | Инфраструктура: CI/CD, Docker, деплой, системные юниты, мониторинг |
| @optimizer | Flash | `direct` | `deepseek-v4-flash` | implementation | Оптимизация: производительность, память, асинхронность, кэш |

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
    defaults:
      direct:
        model: deepseek-v4-flash
      delegate:
        provider: direct
        model: deepseek-v4-flash
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

16 файлов с промптами: `architect`, `coder`, `integration`, `researcher`, `reviewer`, `security` + 10 Flash-агентов.

## Delegation Package (via pipeline_run_agent)

`pipeline_run_agent()` возвращает delegation package с полем `directive`:

- **`directive: "delegate"`** → Pro (только security)
  Оркестратор вызывает `delegate_task(**call_args)` и получает результат.
- **`directive: "direct"`** → Flash (все остальные)
  Оркестратор использует prompt напрямую в своём контексте.

**Правило:** никогда не вызывай `delegate_task` напрямую — всегда через `pipeline_run_agent`.
Порядок: `pipeline_run_agent(state, agent_id)` → прочитать `call_args` → `delegate_task(**call_args)` → `pipeline_advance(state, agent_id)`.

## Pipeline Agents per Category

Не все 16 агентов запускаются в каждом прогоне — только релевантные категории. Это экономия токенов и времени.

| Категория | Агенты | Всего |
|-----------|--------|-------|
| **SECURITY_RELATED** | finder → analyst → researcher → architect → planner → coder → reviewer → **security** → integration → tester → documenter | **11** |
| **BUG_UNKNOWN** | finder → **debugger** → fixer → reviewer → tester | **5** |
| **BUG_KNOWN** | finder → **fixer** → reviewer → tester | **4** |
| **REFACTORING** | finder → analyst → **refactorer** → reviewer → integration → tester | **6** |
| **PERFORMANCE** | finder → analyst → **optimizer** → reviewer → tester | **5** |
| **INFRASTRUCTURE** | finder → **devops** → (reviewer → tester если тестируемо) | **2-4** |
| **DOCUMENTATION** | finder → documenter | **2** |
| **FEATURE** | finder → analyst → architect → planner → coder → reviewer → integration → tester → documenter | **9** |

**Итого:** 16 уникальных агентов. В одном прогоне — от 2 до 11 в зависимости от категории.

```
@finder → @analyst → @researcher → @architect → @planner → @coder
→ @reviewer → @security → @integration → @tester → @documenter
```

## SQLite Kanban (v3.3.0)

Все 11 функций Kanban API работают напрямую с `kanban.db` через `_sqlite_select()` / `_sqlite_update()`:

- `create_parent()`, `create_child()` — INSERT
- `comment()` — INSERT в task_comments
- `block_task()` — UPDATE
- `list_tasks()` — SELECT
- `show_task()` — SELECT с JOIN
- `scan_board()` — SELECT (ядро load/resume/clear)
- `promote()`, `complete()` — UPDATE

**Что это даёт:**
- ✅ Нет молчаливых ошибок от `_kanban()` (возвращала `{}` при любом сбое)
- ✅ Нет зависимости от `hermes kanban` CLI
- ✅ Работает без daemon
- ✅ Быстрее: SQLite вместо subprocess

## Retrospective (v3.3.0)

Пишется JSONL-лог в `~/.hermes/plugins/pipeline/retro/pipe_<id>.jsonl`.

**События:** pipeline_start, agent_start, agent_done, model_routing, convergence, findings, findings_detail, ensemble_gen, ensemble_judge, error, pipeline_clear, default_prompt.

**Для чего:** диагностика прогонов, анализ convergence, детерминизм ensemble, производительность агентов, саморефлексия.

**Конфиг:**
```yaml
pipeline:
  retro:
    enabled: true
    dir: ~/.hermes/plugins/pipeline/retro
    max_files: 100
    auto_analyze: false
```

## Key Files

| File | Purpose |
|------|---------|
| `plugin.yaml` | Manifest (v3.3.0, 12 tools) |
| `__init__.py` | Plugin core: 12 tools + hot-reload MODEL_MAP + default prompt |
| `models.py` | Model config loader: YAML → merge → MODEL_MAP |
| `kanban.py` | **Прямой SQLite** (create_tree, advance, converge, scan_board, resume, reopen) + ensemble |
| `retro.py` | Retrospective logging + auto-analysis |
| `ensemble.py` | Best-of-N: candidate generation + LLM/deterministic judge |
| `classify.py` | Request classification → 8 категорий |
| `agents/*.prompt` | Prompt templates for 16 agents |
| `AGENTS.md` | This file (v3.3.0) |
| `ARCHITECTURE.md` | Full architecture doc (v3.3) |
| `ARCHITECTURE-FIXES.md` | Code review report — 20 bugs found and resolved |
| `config.yaml` | Pipeline config: models, ensemble, retro |
| `CONTRIBUTORS.md` | Список контрибуторов |
| `CHANGELOG.md` | История изменений |
| `skill/pipeline-orchestrator/` | Orchestrator skill |

## Testing & QA Guide

### Unit tests

```bash
# Все тесты
pytest tests/ -v

# По модулям
pytest tests/test_classify.py
pytest tests/test_models.py
pytest tests/test_kanban_convergence.py
pytest tests/test_kanban_integration.py
pytest tests/test_init.py
```

### CI

GitHub Actions в `.github/workflows/test.yml`:
- ruff lint
- bandit SAST
- compile check
- unit tests (pytest)
- **76/76 тестов** (последняя проверка)
