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
    ┌─────────────────────────────────────────┐
    │  @finder     — поиск по коду            │  ← делаю сам (моя модель)
    │  @analyst    — глубокий анализ          │
    │  @researcher — best practices           │  ← delegate_task (OpenRouter free)
    │  @architect  — архитектура решения      │  ← delegate_task (выделенная модель)
    │  @planner    — декомпозиция             │  ← делаю сам
    │  @coder      — реализация               │
    │  @reviewer   — code review              │  ← delegate_task (выделенная модель)
    │  @security   — аудит безопасности       │  ← delegate_task (выделенная модель)
    │  @tester     — тесты                    │
    │  @documenter — документация             │
    └─────────────────────────────────────────┘
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

**Как я определяю, что запускать:**

Я смотрю на ключевые слова в твоём сообщении. Например:
- `auth`, `jwt`, `token`, `password`, `security` → **SECURITY_RELATED** (полный пайплайн с аудитом)
- `refactor`, `рефакторинг` → **REFACTORING** (анализ + рефакторинг + ревью)
- `bug`, `crash`, `баг`, `сломалось` → **BUG_UNKNOWN** (диагностика + фикс)
- `fix`, `исправь` → **BUG_KNOWN** (точечный фикс)
- `docs`, `документация`, `readme` → **DOCUMENTATION** (только документирование)
- Если ничего не подошло → **FEATURE** (полный пайплайн с архитектором)
- Если задача очевидно простая — пайплайн не запускается, делаю сразу

Ты можешь и сам явно сказать:

```
запусти пайплайн на добавление JWT
сделай security-аудит этого кода
запусти рефакторинг через пайплайн
```

Но в большинстве случаев я сам понимаю, что нужно.

### Как останавливать и смотреть статус

После каждого этапа я спрашиваю **продолжаем?** — это главный механизм контроля.

Статус активного пайплайна я помню в памяти, могу показать в любой момент:
- Спроси «что сейчас в пайплайне?» или «на каком этапе?»
- Если хочешь отменить — скажи «стоп», «отмена», «хватит»

Состояние сохраняется на диск (`state.json`) — если сессия прервётся, я могу продолжить при следующем запуске.

### Категории пайплайнов

| Категория | Пайплайн | Триггеры |
|-----------|----------|----------|
| **SECURITY_RELATED** | finder → analyst → researcher → architect → planner → coder → reviewer → security → tester → documenter | auth, jwt, password, token, security |
| **BUG_UNKNOWN** | finder → debugger → fixer → reviewer → tester | crash, exception, broken |
| **BUG_KNOWN** | finder → fixer → reviewer → tester | fix, исправь |
| **REFACTORING** | finder → analyst → refactorer → reviewer → tester | refactor, рефакторинг |
| **PERFORMANCE** | finder → analyst → optimizer → reviewer → tester | optimize, slow, memory |
| **INFRASTRUCTURE** | finder → devops → reviewer → tester | docker, deploy, config |
| **DOCUMENTATION** | finder → documenter | docs, readme, документация |
| **FEATURE** | finder → analyst → architect → planner → coder → reviewer → tester → documenter | всё остальное |

### Конвергенция (новое)

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

### Как менять модели агентов

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

### Структура проекта

```
hermes-pipeline-plugin/
├── __init__.py          # Ядро плагина — схемы, хендлеры, MODEL_MAP (7 tools)
├── classify.py          # Классификация запросов (8 категорий)
├── state.py             # Состояние + конвергенция (findings, fingerprint, max_rounds)
├── plugin.yaml          # Манифест плагина
├── AGENTS.md            # Шпаргалка для AI-ассистентов
├── ARCHITECTURE.md      # Архитектура плагина
├── pyproject.toml       # Ruff-линтер конфиг + build-system
├── LICENSE              # MIT
├── agents/
│   ├── architect.prompt    # Промпт для @architect
│   ├── researcher.prompt   # Промпт для @researcher
│   ├── reviewer.prompt     # Промпт для @reviewer
│   └── security.prompt     # Промпт для @security
├── skill/
│   └── pipeline-orchestrator/  # Скилл оркестратора
├── .github/workflows/       # CI (ruff + bandit + pytest)
└── tests/
    ├── test_classify.py  # 16 тестов классификации
    ├── test_state.py     # 8 тестов state persistence
    └── test_init.py      # 12 тестов ядра плагина
```

### Безопасность

- **Path traversal protection** — `handle_prompt()` проверяет, что файл агента внутри `agents/`
- **Нет хардкоженных ключей** — все credentials через Hermes credential pool
- **CI quality gates** — ruff (линтер) + bandit (SAST) + pytest перед каждым мержем
- **state.json** — живёт локально, не в git

### Требования

- Hermes Agent (с поддержкой `register_tool` и `delegate_task`)
- Python ≥ 3.11
- Для delegate-агентов (architect, reviewer, security) — настроенный delegation провайдер
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

### How to Change Models

Edit `MODEL_MAP` in [`__init__.py`](__init__.py):

```python
MODEL_MAP = {
    "finder":       {"provider": "direct", "model": "deepseek-v4-flash"},
    "architect":    {"provider": "delegate", "model": "deepseek-v4-pro"},
    "researcher":   {"provider": "delegate_free", "model": "openrouter/free"},
}
```

### Pipeline Categories

| Category | Pipeline | Triggers |
|----------|----------|----------|
| **SECURITY_RELATED** | finder → analyst → researcher → architect → planner → coder → reviewer → security → tester → documenter | auth, jwt, password |
| **BUG_UNKNOWN** | finder → debugger → fixer → reviewer → tester | crash, exception |
| **BUG_KNOWN** | finder → fixer → reviewer → tester | fix |
| **REFACTORING** | finder → analyst → refactorer → reviewer → tester | refactor |
| **PERFORMANCE** | finder → analyst → optimizer → reviewer → tester | slow, memory |
| **INFRASTRUCTURE** | finder → devops → reviewer → tester | docker, deploy |
| **DOCUMENTATION** | finder → documenter | docs |
| **FEATURE** | finder → analyst → architect → planner → coder → reviewer → tester → documenter | default |

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
