# AGENTS.md — Pipeline Plugin (v3.8.3, SQLite-native + handlers/)

## What This Is

Плагин-оркестратор multi-agent пайплайнов для Hermes Agent.
**Variant C:** `state.json` удалён. `kanban.db` — единое состояние.
**v3.8.3:** 17 хендлеров в `handlers/__init__.py`, dead code удалён, модели пофикшены, инфраструктура скилов.

### v3.8.2–v3.8.3 — dead code removal, models fix, skill infra

- **Dead code** — `kanban.py::generate_candidates`, `kanban.py::judge_candidates` удалены (дубли из `ensemble.py`). 10 F821 errors устранены.
- **Модели** — все Flash-агенты переключены на `delegate/polza/deepseek-v4-flash`
- **17 хендлеров** вынесены из `__init__.py` (892→280 строк) в `handlers/__init__.py`

### v3.8.2 — plugin compliance

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

### Полная таблица агентов и моделей (v3.8.2)

| Агент | Тип | Провайдер | Дефолтная модель | Контекстные секции | Описание |
|-------|-----|-----------|-----------------|-------------------|----------|
|| @finder | Flash | `delegate` | `polza/deepseek-v4-flash` | research | Сбор информации: чтение кода, файлов и конфигов, разведка перед анализом |
|| @analyst | Flash | `delegate` | `polza/deepseek-v4-flash` | research | Анализ и диагностика: поиск корня проблемы, разбор логов, выявление закономерностей |
|| @researcher | Flash | `delegate` | `polza/deepseek-v4-flash` | research | Внешние исследования: best practices, документация, альтернативы |
|| @architect | Flash | `delegate` | `polza/deepseek-v4-flash` | research, planning | Проектирование: архитектура изменений, выбор компонентов, связи модулей |
|| @planner | Flash | `delegate` | `polza/deepseek-v4-flash` | planning, infrastructure | Планирование: разбивка на подзадачи, оценка объёма, план шагов |
|| @coder | Flash | `delegate` | `polza/deepseek-v4-flash` | implementation, planning | Разработка: написание кода, реализация фич, имплементация логики |
|| @fixer | Flash | `delegate` | `polza/deepseek-v4-flash` | implementation | Исправление: патчи багов, замена сломанных вызовов, обходы проблем |
|| @refactorer | Flash | `delegate` | `polza/deepseek-v4-flash` | implementation | Рефакторинг: улучшение структуры, устранение дублирования, выделение функций |
|| @reviewer | Flash | `delegate` | `polza/deepseek-v4-flash` | implementation, research | Код-ревью: проверка качества, логические ошибки, рекомендации |
|| @security | **Pro** | **`delegate`** | **`deepseek-v4-pro`** | implementation, research | Аудит безопасности: XSS, SQL-инъекции, утечки данных, права доступа |
|| @integration | Flash | `delegate` | `polza/deepseek-v4-flash` | implementation, documentation, infrastructure | Консистентность: кросс-файловые связи, импорты, типы, совместимость API |
|| @tester | Flash | `delegate` | `polza/deepseek-v4-flash` | implementation | Тестирование: написание тестов, прогон, регрессия, assertions |
|| @debugger | Flash | `delegate` | `polza/deepseek-v4-flash` | implementation | Отладка: пошаговый поиск первопричины, стек, анализ переменных |
|| @documenter | Flash | `delegate` | `polza/deepseek-v4-flash` | implementation, documentation | Документация: README, AGENTS.md, changelog, комментарии, инструкции |
|| @devops | Flash | `delegate` | `polza/deepseek-v4-flash` | infrastructure | Инфраструктура: CI/CD, Docker, деплой, системные юниты, мониторинг |
|| @optimizer | Flash | `delegate` | `polza/deepseek-v4-flash` | implementation | Оптимизация: производительность, память, асинхронность, кэш |
|| **@quality** | Flash | `delegate` | `deepseek-v4-flash` | implementation | Quality gates (ruff/bandit/compileall/pytest) |

**Всего:** 17 агентов (16 Flash `delegate/polza` + @security на Pro-делегации).

## call_args контракт (v3.8.2)

Начиная с v3.8.2, `pipeline_run_agent()` и `build_judge_call_args()` возвращают call_args строго в формате:

```python
call_args = {"goal": prompt}
```

Единственное поле `goal` — упрощение контракта между плагином и оркестратором. Все остальные поля (`prompt`, `provider`, `model`, `description`, `config`) больше не передаются. Всё, что нужно агенту, должно быть в самом промпте.

### Как использовать

```python
pkg = pipeline_run_agent(state, 'coder')
delegate_task(**pkg.call_args)  # pkg.call_args = {'goal': prompt}
pipeline_advance(state, 'coder')
```

Для Judge:
```python
result = judge_candidates(request, candidates, judge_mode='llm')
delegate_task(**result['judge_call_args'])  # {'goal': judge_prompt}
```

### Как работают модели (v3.8.2)

Три режима выполнения:

- **`delegate`** (Polza Flash) — я вызываю `delegate_task` с `polza/deepseek-v4-flash`. Все Flash-агенты работают через этот режим. Дёшево, быстро.
- **`delegate`** (Pro) — @security вызывает `delegate_task` с `deepseek-v4-pro`. Дороже, но лучше для audit безопасности.
- **`direct`** — (устарел) раньше использовался для Flash-агентов в v3.7.x, заменён на `delegate` через Polza в v3.8.2.

### Настройка через конфиг

**`~/.hermes/plugins/pipeline/config.yaml`**

```yaml
pipeline:
  models:
    defaults:
      delegate:
        provider: polza
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
defaults.delegate        ← средний (групповая настройка по типу делегации)
BUILTIN_MODEL_MAP        ← низший (хардкод в models.py)
```

Если секция `pipeline.models` отсутствует или файл повреждён — используется только `BUILTIN_MODEL_MAP`.

## AGENT_CONTEXT_FIELDS (v3.8.2)

Определено в `handlers/__init__.py`. Каждый агент получает только свои секции контекста:

| Агент | Секции контекста |
|-------|-----------------|
| @finder | research |
| @analyst | research |
| @researcher | research |
| @architect | research, planning |
| @planner | planning, infrastructure |
| @coder | implementation, planning |
| @fixer | implementation |
| @refactorer | implementation |
| @reviewer | implementation, research |
| @security | implementation, research |
| @integration | implementation, documentation, infrastructure |
| @tester | implementation |
| @debugger | implementation |
| @documenter | implementation, documentation |
| @devops | infrastructure |
| @optimizer | implementation |
| **@quality** | **implementation** |

### quality.prompt

Промпт для @quality (агент quality gates):

```
Ты — @quality в пайплайне Pipeline Plugin.

## Задача
Запусти quality gates для проекта: ruff → bandit → compileall → pytest.
Если хоть один гейт упал — верни FAIL с деталями.
Если все прошли — верни PASS.

## Контекст
Твои секции контекста: implementation
```

Файл: `agents/quality.prompt` (создан в v3.8.2).

## Agent .prompt файлы

Каждый агент имеет `.prompt` файл в `agents/`. Если файл отсутствует — генерируется default prompt из `AGENT_CONTEXT_FIELDS`.

17 файлов с промптами: `architect`, `coder`, `integration`, `researcher`, `reviewer`, `security` + 11 Flash-агентов (включая `quality`).

## Delegation Package (via pipeline_run_agent)

`pipeline_run_agent()` возвращает delegation package с полем `directive`:

- **`directive: "delegate"`** → Pro (security) или Polza Flash (все остальные)
  Оркестратор вызывает `delegate_task(**call_args)` и получает результат.

**Правило:** никогда не вызывай `delegate_task` напрямую — всегда через `pipeline_run_agent`.
Порядок: `pipeline_run_agent(state, agent_id)` → прочитать `call_args` → `delegate_task(**call_args)` → `pipeline_advance(state, agent_id)`.

## Pipeline Agents per Category

Не все 17 агентов запускаются в каждом прогоне — только релевантные категории. Это экономия токенов и времени.

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
| `plugin.yaml` | Manifest (v3.8.2, 12 tools) |
| `__init__.py` | Plugin core: 12 tool schemas + register() — handlers extracted to handlers/ |
| `models.py` | Model config loader: YAML → merge → MODEL_MAP (hot-reload по mtime) |
| `handlers/__init__.py` | 12 tool handlers + _build_agent_prompt + AGENT_CONTEXT_FIELDS |
| `kanban.py` | **Прямой SQLite** (create_tree, advance, converge, scan_board, resume, reopen) + ensemble |
| `retro.py` | Retrospective logging + auto-analysis |
| `ensemble.py` | Best-of-N: candidate generation + LLM/deterministic judge |
| `classify.py` | Request classification → 8 категорий (+ quality pipeline) |
| `convergence.py` | Deterministic convergence engine (extracted from kanban.py) |
| `agents/*.prompt` | Prompt templates for 17 agents (включая @quality) |
| `AGENTS.md` | This file (v3.8.2) |
| `ARCHITECTURE.md` | Full architecture doc (v3.8.2) |
| `ARCHITECTURE-FIXES.md` | Code review report — 20 bugs found and resolved |
| `config.yaml` | Pipeline config: models, ensemble, retro |
| `CONTRIBUTORS.md` | Список контрибуторов |
| `CHANGELOG.md` | История изменений |
| `skill/pipeline-orchestrator/` | Orchestrator skill (v3.8.2) |
| `skill/pipeline-audit-checklist/` | Audit checklist skill |
| `skill/pipeline-ensemble/` | Best-of-N ensemble skill |

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
- **311/311 тестов** (v3.8.2)

## Memory Setup

Pipeline plugin использует **Mnemosyne** для сохранения контекста между сессиями. Вот что нужно настроить.

### Если используется Mnemosyne (рекомендуется)

**Persona permanent (обязательно):** Правило auto-resume вшивается в system prompt при каждом старте:

```text
При старте каждой новой сессии ОБЯЗАТЕЛЬНО:
1) pipeline_resume() — проверить активный пайплайн на kanban доске
2) skill_view('pipeline-orchestrator') — загрузить скил пайплайна
3) Если pipeline_resume() вернул стейт — не создавать новый пайплайн, а продолжить
```

Установка:
```bash
# Через Mnemosyne API
mnemosyne_remember(content="<правило>", importance=1.0, scope="global", source="rule")
mnemosyne_persona_promote(memory_id="<id>", tier="permanent")
```

**Canonical backup (опционально):**
```bash
mnemosyne_remember(content="[canonical:workflow/pipeline_auto_resume] ...", importance=0.95, scope="global")
```

### Если используется стандартная память (MEMORY.md)

Добавить в `~/.hermes/memories/MEMORY.md`:

```text
Pipeline auto-resume: при старте сессии вызывать pipeline_resume() и skill_view('pipeline-orchestrator'). Если есть активный пайплайн на kanban доске — продолжать его, не создавать новый.
```

Конфиг `~/.hermes/config.yaml`:
```yaml
memory:
  memory_enabled: true
  user_profile_enabled: true
  memory_char_limit: 2200
```

### Форматирование ответов

Чтобы таблицы и Markdown отображались корректно:

```yaml
display:
  final_response_markdown: auto   # не strip — сохраняет разметку
```

Скилы для загрузки:
- `response-formatting` — базовые правила (разрешены pipe-таблицы)
- `telegram-rich-formatting` — Telegram Bot API 10.1 rich messages
