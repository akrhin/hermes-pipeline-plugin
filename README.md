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

```
Ты:    "/pipeline добавь JWT аутентификацию"
              │
              ▼
    pipeline_classify("добавь JWT аутентификацию")
              │
              ▼
    { category: "SECURITY_RELATED",
      pipeline: [finder, analyst, researcher, architect,
                 planner, coder, reviewer, security, tester, documenter] }
              │
              ▼
    ┌─────────────────────────────────────────┐
    │  @finder     — поиск по коду            │  ← сам (Flash)
    │  @analyst    — глубокий анализ          │
    │  @researcher — best practices           │  ← OpenRouter free
    │  @architect  — архитектура решения      │  ← delegate (Pro)
    │  @planner    — декомпозиция             │  ← сам (Flash)
    │  @coder      — реализация               │
    │  @reviewer   — code review              │  ← delegate (Pro)
    │  @security   — аудит безопасности        │  ← delegate (Pro)
    │  @tester     — тесты                    │
    │  @documenter — документация             │
    └─────────────────────────────────────────┘
```

**Checkpoint'ы на каждом этапе:**
1. ✅ Исследование готово → **продолжаем?**
2. ✅ План готов → **начинаем реализацию?**
3. ✅ Код написан → **запускаем quality gates?** (авто)
4. ✅ Пайплайн завершён

### Как пользоваться

Просто напиши задачу на русском или английском:

```
/pipeline добавь JWT аутентификацию в проект
/pipeline refactor UserService — раздутый класс
/pipeline оптимизируй запросы к БД
/pipeline настрой CI/CD через GitHub Actions
```

Плагин сам:
1. **Классифицирует** запрос → выбирает категорию и список агентов
2. **Проводит исследование** — находит файлы, анализирует код
3. **Проектирует решение** — архитектор предлагает план
4. **Реализует** — пишет код
5. **Проверяет качество** — code review + security audit + тесты
6. **Документирует** — обновляет README/архитектуру

Каждый этап — с checkpoint'ом: ты подтверждаешь или корректируешь.

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

### Быстрые команды

| Команда | Что делает |
|---------|------------|
| `/pipeline <задача>` | Полный пайплайн: research → plan → code → review → security → test → docs |
| `/review <файл>` | Только code review |
| `/test <файл>` | Только тесты |
| `/security <файл>` | Только security audit |
| `/status` | Статус текущего пайплайна |
| `/abort` | Отменить пайплайн |

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
├── __init__.py          # Ядро плагина — схемы, хендлеры, MODEL_MAP
├── classify.py          # Классификация запросов (8 категорий)
├── state.py             # Состояние пайплайна (JSON на диске, TTL 24h)
├── plugin.yaml          # Манифест плагина
├── AGENTS.md            # Шпаргалка для AI-ассистентов
├── ARCHITECTURE.md      # Архитектура плагина
├── pyproject.toml       # Ruff-линтер конфиг + build-system
├── LICENSE              # MIT
├── .github/workflows/   # CI (ruff + bandit + pytest)
├── agents/
│   ├── architect.prompt    # Промпт для @architect
│   ├── researcher.prompt   # Промпт для @researcher
│   ├── reviewer.prompt     # Промпт для @reviewer
│   └── security.prompt     # Промпт для @security
├── skill/
│   └── pipeline-orchestrator/  # Скилл оркестратора
├── .cursor/backlog/       # История изменений
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

Pipeline Plugin adds 6 tools to Hermes Agent that orchestrate multi-agent pipelines:

| Tool | Purpose |
|------|---------|
| `pipeline_classify` | Classify request → category + agent list |
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

### Quick Commands

| Command | What it does |
|---------|--------------|
| `/pipeline <task>` | Full pipeline: research → plan → code → review → security → test → docs |
| `/review <file>` | Code review only |
| `/test <file>` | Write/run tests only |
| `/security <file>` | Security audit only |
| `/status` | Show current pipeline state |
| `/abort` | Cancel current pipeline |

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
