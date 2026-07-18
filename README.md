# 🔱 Hermes Pipeline Plugin

> Multi-agent pipeline orchestrator for [Hermes Agent](https://github.com/NousResearch/hermes-agent).
> Автоматизирует сложные задачи (фичи, багфиксы, рефакторинг, security audit)
> через пайплайн специализированных агентов с quality gates.

[![Tests](https://github.com/akrhin/hermes-pipeline-plugin/actions/workflows/test.yml/badge.svg)](https://github.com/akrhin/hermes-pipeline-plugin/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## 🇷🇺 Русский

### Что это

Плагин-оркестратор для Hermes Agent, реализующий multi-agent пайплайны с quality gates.
Позволяет автоматизировать сложные задачи — от разведки и планирования до реализации,
ревью, безопасности и документации — одной командой.

### Установка

**Нужно установить два компонента:** плагин (инструменты) + скилл (оркестрация).

```bash
# 1. Плагин — Python-инструменты (классификация, состояние, модели)
git clone https://github.com/akrhin/hermes-pipeline-plugin.git ~/git/hermes-pipeline-plugin
ln -sf ~/git/hermes-pipeline-plugin ~/.hermes/plugins/pipeline

# 2. Скилл-оркестратор — инструкции для агента (обязательно!)
ln -sf ~/git/hermes-pipeline-plugin/skill/pipeline-orchestrator \
      ~/.hermes/skills/hermes/pipeline-orchestrator
```

Пропиши в `~/.hermes/config.yaml`:
```yaml
plugins:
  enabled:
    - pipeline
```

Перезагрузи:
```bash
# Если Hermes Gateway:
systemctl --user restart hermes-gateway
# Если CLI: просто перезапусти сессию
```

### Как работает

**Нет никаких `/pipeline`, `/review`, `/security` команд.** Плагин не принимает команды.
Реальный сценарий:

```
Ты:    "добавь JWT аутентификацию в проект"
              │
              ▼ (я анализирую твоё сообщение по ключевым словам)
              │
    Сработал триггер: auth, jwt, token → SECURITY_RELATED
              │
              ▼
    Я запускаю пайплайн:
    ┌────────────────────────────────────────────────────┐
    │  @finder      — поиск по коду                      │  ← моя модель
    │  @analyst     — глубокий анализ                    │
    │  @researcher  — best practices                     │  ← OpenRouter free
    │  @architect   — архитектура решения                │  ← выделенная модель
    │  @planner     — декомпозиция                       │  ← моя модель
    │  @coder       — реализация                         │
    │  @reviewer    — code review                        │  ← выделенная модель
    │  @security    — аудит безопасности                 │  ← выделенная модель
    │  @integration — проверка интеграции (cross-file)   │  ← выделенная модель
    │  @tester      — тесты                              │  ← моя модель
    │  @documenter  — документация                       │
    └────────────────────────────────────────────────────┘
```

Плагин только даёт мне инструменты (`pipeline_classify`, `pipeline_save` и т.д.).
Оркестрацию делаю я — через скилл `pipeline-orchestrator`, который загружается
автоматически, когда я вижу в твоём сообщении ключевые слова.

Checkpoint'ы — я спрашиваю тебя после каждого этапа:

```
📋 Исследование готово:
  Найдено 3 файла, стек: Go 1.22 + gin
  Продолжаем?
→ ты: "да"
```

### Как задать задачу

Просто пиши на русском или английском — я сам определяю, нужен ли пайплайн:

```
добавь JWT аутентификацию в проект
refactor UserService — раздутый класс
оптимизируй запросы к БД
настрой CI/CD через GitHub Actions
проверь этот код на уязвимости
напиши документацию для API
```

Ты можешь и сам явно сказать:

```
запусти пайплайн на добавление JWT
сделай security-аудит этого кода
запусти рефакторинг через пайплайн
```

### Категории пайплайнов

| Категория | Пайплайн | Триггеры |
|-----------|----------|----------|
| **SECURITY_RELATED** | finder → analyst → researcher → architect → planner → coder → reviewer → security → **integration** → tester → documenter | auth, jwt, password, token, security |
| **BUG_UNKNOWN** | finder → debugger → fixer → reviewer → tester | crash, exception, broken |
| **BUG_KNOWN** | finder → fixer → reviewer → tester | fix, исправь |
| **REFACTORING** | finder → analyst → refactorer → reviewer → **integration** → tester | refactor, рефакторинг |
| **PERFORMANCE** | finder → analyst → optimizer → reviewer → tester | optimize, slow, memory |
| **INFRASTRUCTURE** | finder → devops → reviewer → tester | docker, deploy, config |
| **DOCUMENTATION** | finder → documenter | docs, readme, документация |
| **FEATURE** | finder → analyst → architect → planner → coder → reviewer → **integration** → tester → documenter | всё остальное |

### Конвергенция

Пайплайн — это **когерентный цикл**, а не одноразовый конвейер:

1. `coder` пишет код
2. `reviewer + security + tester` проверяют
3. Если есть **P0/P1** баги → возврат к `coder` с замечаниями
4. Максимум **3 раунда** (hard stop в коде)
5. Если те же баги второй раз → **STUCK** (escalation)
6. Если P0/P1 = 0 → **converged → documenter**

Severity:
- **P0** — correctness/security, блокирует merge (обязательно исправить)
- **P1** — degraded behaviour (исправить или remediation plan)
- **P2** — style/naming (advisory, не блокирует)

Решения `pipeline_convergence`:
- `continue` → вернуть `coder` с замечаниями
- `converged` → идти к `documenter`
- `stuck` → escalation пользователю
- `maxed_out` → показать что недоделано

### Как менять модели

Модели заданы в `MODEL_MAP` в [`__init__.py`](__init__.py):

| Провайдер | Что значит |
|-----------|------------|
| `direct` | Агент работает сам — твоя текущая модель |
| `delegate` | Спавнит под-агента через `delegate_task()` |
| `delegate_free` | Спавнит под-агента через OpenRouter free |

Открой файл и поменяй нужную модель:

```bash
vim ~/.hermes/plugins/pipeline/__init__.py
# Или просто скажи агенту:
# "Смени @architect на claude-sonnet-4"
```

### Kanban Dashboard (автоматическая)

Начиная с v1.2.0, пайплайн **автоматически** ведёт доску `pipeline` через встроенный модуль `kanban.py`:

| Событие | Действие на доске |
|---------|-------------------|
| Старт пайплайна | Создаётся task с idempotency-key |
| Каждый раунд конвергенции | Комментарий с P0/P1/P2 счётом |
| Converged | Task → complete |
| Stuck | Task → blocked (нужен human review) |
| Maxed out | Task → complete с пометкой |
| Очистка/отмена | Task → complete (Cancelled) |

Никаких ручных команд — всё делает плагин. Доска `pipeline` должна быть создана заранее:

```bash
hermes kanban boards create pipeline "Pipeline tasks"
hermes kanban boards switch pipeline
```

Смотреть статус:
```bash
hermes kanban ls          # список задач
hermes kanban show <id>   # детали задачи с комментариями
hermes kanban stats       # статистика доски
```

### Требования

- Hermes Agent (с поддержкой `register_tool` и `delegate_task`)
- Python ≥ 3.11
- Для delegate-агентов (architect, reviewer, security, integration) — настроенный delegation провайдер
- Для delegate_free (researcher) — OpenRouter API ключ в `OPENROUTER_API_KEY`

---

## 🇬🇧 English

### Overview

Pipeline Plugin adds 7 tools to Hermes Agent that orchestrate multi-agent pipelines:

| Tool | Purpose |
|------|---------|
| `pipeline_classify` | Classify request → category + agent list |
| **`pipeline_convergence`** | **Evaluate convergence (deterministic, no LLM)** |
| `pipeline_save` | Save pipeline state (resumable) |
| `pipeline_load` | Load saved state |
| `pipeline_clear` | Clear state |
| `agent_prompt` | Build agent prompt with context |
| `agent_model` | Get provider + model for an agent |

### Installation

Two components required — plugin (tools) + skill (orchestration):

```bash
# 1. Plugin — Python tools
git clone https://github.com/akrhin/hermes-pipeline-plugin.git ~/git/hermes-pipeline-plugin
ln -sf ~/git/hermes-pipeline-plugin ~/.hermes/plugins/pipeline

# 2. Skill — agent orchestration instructions
ln -sf ~/git/hermes-pipeline-plugin/skill/pipeline-orchestrator \
      ~/.hermes/skills/hermes/pipeline-orchestrator

# 3. Enable & restart
hermes plugins enable pipeline
systemctl --user restart hermes-gateway   # or restart CLI session
```

### Pipeline Categories

| Category | Pipeline | Triggers |
|----------|----------|----------|
| **SECURITY_RELATED** | finder → analyst → researcher → architect → planner → coder → reviewer → security → **integration** → tester → documenter | auth, jwt, password |
| **BUG_UNKNOWN** | finder → debugger → fixer → reviewer → tester | crash, exception |
| **BUG_KNOWN** | finder → fixer → reviewer → tester | fix |
| **REFACTORING** | finder → analyst → refactorer → reviewer → **integration** → tester | refactor |
| **PERFORMANCE** | finder → analyst → optimizer → reviewer → tester | slow, memory |
| **INFRASTRUCTURE** | finder → devops → reviewer → tester | docker, deploy |
| **DOCUMENTATION** | finder → documenter | docs |
| **FEATURE** | finder → analyst → architect → planner → coder → reviewer → **integration** → tester → documenter | default |

### Kanban Dashboard (automatic)

Since v1.2.0, pipelines **automatically** track progress on the `pipeline` board via `kanban.py`:

| Event | Board action |
|-------|-------------|
| Pipeline start | Task created with idempotency-key |
| Convergence round | Comment with P0/P1/P2 counts |
| Converged | Task → complete |
| Stuck | Task → blocked (human review) |
| Maxed out | Task → complete (flagged) |
| Clear/cancel | Task → complete (Cancelled) |

No manual `hermes kanban` commands needed — the plugin handles it. Create the board once:

```bash
hermes kanban boards create pipeline "Pipeline tasks"
hermes kanban boards switch pipeline
```

Monitor:
```bash
hermes kanban ls          # list tasks
hermes kanban show <id>   # task details + comments
hermes kanban stats       # board statistics
```

Edit `MODEL_MAP` in [`__init__.py`](__init__.py):

```python
MODEL_MAP = {
    "finder":       {"provider": "direct", "model": "deepseek-v4-flash"},
    "architect":    {"provider": "delegate", "model": "deepseek-v4-pro"},
    "researcher":   {"provider": "delegate_free", "model": "openrouter/free"},
}
```

---

## Development

```bash
# Install deps
pip install pytest ruff bandit

# Run tests
python -m pytest tests/ -q -v

# Lint
ruff check .

# SAST
bandit -r . -ll -q
```

## License

MIT
