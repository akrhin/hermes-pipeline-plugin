# 🔱 Hermes Pipeline Plugin

> Multi-agent pipeline orchestrator for [Hermes Agent](https://github.com/NousResearch/hermes-agent).
> Автоматизирует сложные задачи (фичи, багфиксы, рефакторинг, security audit) через пайплайн специализированных агентов с quality gates.

[![Tests](https://github.com/akrhin/hermes-pipeline-plugin/actions/workflows/test.yml/badge.svg)](https://github.com/akrhin/hermes-pipeline-plugin/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## 🇬🇧 English

### Overview

Pipeline Plugin adds 6 tools to Hermes Agent that orchestrate multi-agent pipelines:

| Tool | Purpose |
|------|---------|
| `pipeline_classify` | Classify user request → pipeline category + agent list |
| `pipeline_save` | Save pipeline state (resumable after restart) |
| `pipeline_load` | Load saved pipeline state |
| `pipeline_clear` | Clear pipeline state |
| `agent_prompt` | Build a prompt for a specific agent with context injection |
| `agent_model` | Get provider + model for a specific agent |

### How It Works

```
You say:   "/pipeline Add JWT authentication"
               │
               ▼
    pipeline_classify("Add JWT auth")
               │
               ▼
    { category: "SECURITY_RELATED",
      pipeline: [finder, analyst, researcher, architect,
                 planner, coder, reviewer, security, tester, documenter] }
               │
               ▼
    ┌─────────────────────────────────────────┐
    │       @finder    — codebase search       │  ← done directly
    │       @analyst   — deep analysis         │
    │       @researcher — best practices        │  ← via OpenRouter free
    │       @architect — solution design       │  ← via delegate_task (Pro)
    │       @planner   — task decomposition    │  ← done directly
    │       @coder     — implementation        │
    │       @reviewer  — code review           │  ← via delegate_task (Pro)
    │       @security  — vulnerability audit   │  ← via delegate_task (Pro)
    │       @tester    — tests                 │
    │       @documenter — docs                 │
    └─────────────────────────────────────────┘
```

Each pipeline has **checkpoints** where the user confirms before proceeding:
1. ✅ Research complete → **continue?**
2. ✅ Plan ready → **start implementation?**
3. ✅ Code written → **run quality gates?** (auto)
4. ✅ Pipeline complete

### How to Change Models

Models are defined in [`__init__.py`](__init__.py) — the `MODEL_MAP` dict:

```python
MODEL_MAP = {
    # Direct agents (use your current Hermes model)
    "finder":       {"provider": "direct", "model": "deepseek-v4-flash"},
    "analyst":      {"provider": "direct", "model": "deepseek-v4-flash"},
    "planner":      {"provider": "direct", "model": "deepseek-v4-flash"},
    "coder":        {"provider": "direct", "model": "deepseek-v4-flash"},
    "tester":       {"provider": "direct", "model": "deepseek-v4-flash"},
    "documenter":   {"provider": "direct", "model": "deepseek-v4-flash"},

    # Delegate agents (called via delegate_task → V4 Pro by default)
    "architect":    {"provider": "delegate", "model": "deepseek-v4-pro"},
    "reviewer":     {"provider": "delegate", "model": "deepseek-v4-pro"},
    "security":     {"provider": "delegate", "model": "deepseek-v4-pro"},

    # Free agents (called via OpenRouter free tier)
    "researcher":   {"provider": "delegate_free", "model": "openrouter/free"},
    "commenter":    {"provider": "delegate_free", "model": "openrouter/free"},
}
```

**Provider types:**

| Provider | Meaning |
|----------|---------|
| `direct` | Agent does the work itself — uses **your current Hermes model** |
| `delegate` | Spawns a sub-agent via `delegate_task()` using your configured delegation model |
| `delegate_free` | Spawns a sub-agent with OpenRouter free model (for cheap research/comment tasks) |

**To change any model — just edit the dict.** Or tell the agent "change @architect to claude-sonnet-4" and it'll do it for you.

### Pipeline Categories

| Category | Pipeline | Triggers |
|----------|----------|----------|
| **SECURITY_RELATED** | finder → analyst → researcher → architect → planner → coder → reviewer → security → tester → documenter | auth, jwt, password, token, security |
| **BUG_UNKNOWN** | finder → debugger → fixer → reviewer → tester | crash, exception, broken |
| **BUG_KNOWN** | finder → fixer → reviewer → tester | fix, исправь |
| **REFACTORING** | finder → analyst → refactorer → reviewer → tester | refactor, рефакторинг |
| **PERFORMANCE** | finder → analyst → optimizer → reviewer → tester | optimize, slow, memory |
| **INFRASTRUCTURE** | finder → devops → reviewer → tester | docker, deploy, config |
| **DOCUMENTATION** | finder → documenter | docs, readme, документация |
| **FEATURE** | finder → analyst → architect → planner → coder → reviewer → tester → documenter | default (everything else) |

### Quick Commands

| Command | What it does |
|---------|--------------|
| `/pipeline Add JWT auth` | Full pipeline: research → plan → code → review → security → test → docs |
| `/review auth.go` | Code review only (one file) |
| `/test auth_test.go` | Write/run tests only |
| `/security auth.go` | Security audit only |
| `/status` | Show current pipeline state |
| `/abort` | Cancel current pipeline |

---

## 🇷🇺 Русский

### Что это

Плагин-оркестратор для Hermes Agent, реализующий multi-agent пайплайны с quality gates. Позволяет автоматизировать сложные задачи — от разведки и планирования до реализации, ревью, безопасности и документации — одной командой.

## Installation

### 1. Plugin (Python)

```bash
git clone https://github.com/akrhin/hermes-pipeline-plugin.git ~/git/hermes-pipeline-plugin
ln -sf ~/git/hermes-pipeline-plugin ~/.hermes/plugins/pipeline
```

Enable in `~/.hermes/config.yaml`:
```yaml
plugins:
  enabled:
    - pipeline
```

### 2. Orchestrator Skill (agent instructions)

The plugin is just the toolbox. The **orchestration logic** lives in a Hermes skill that tells the agent how to use it:

```bash
# Symlink the skill into Hermes skills directory
ln -sf ~/git/hermes-pipeline-plugin/skill/pipeline-orchestrator ~/.hermes/skills/hermes/pipeline-orchestrator
```

Once installed, the skill auto-loads when you send `/pipeline`, `/review`, `/test`, `/security`, `/status`, or any `/abort` command — the agent knows exactly how to classify, delegate, checkpoint, and resume.

> **Why two components?** The plugin handles tool registration (classification, state management, model routing). The skill handles orchestration logic (how to run a pipeline, checkpoint flow, revision loops). Both are needed for the full experience.

### 3. Restart

```bash
# If using Hermes Gateway:
systemctl --user restart hermes-gateway

# If using CLI: restart the session
```

### Требования

- Hermes Agent (любая версия с поддержкой `register_tool` и `delegate_task`)
- Python ≥ 3.11
- Для delegate-агентов (architect, reviewer, security) — настроенный delegation провайдер
- Для delegate_free (researcher) — OpenRouter API ключ в `OPENROUTER_API_KEY`

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

### Как менять модели агентов

```bash
# Открой файл плагина:
vim ~/.hermes/plugins/pipeline/__init__.py
# Найди MODEL_MAP — словарь в середине файла
# Поменяй нужную модель:
```

Или просто скажи агенту:

> "Смени @architect на claude-sonnet-4"
> "Используй deepseek-chat для @reviewer"
> "Сделай @tester на direct, а @architect на openai/gpt-4o"

### Структура проекта

```
hermes-pipeline-plugin/
├── __init__.py          # Ядро плагина — схемы, хендлеры, MODEL_MAP
├── classify.py          # Классификация запросов (keyword-based, 8 категорий)
├── state.py             # Состояние пайплайна (JSON на диске, TTL 24h)
├── plugin.yaml          # Манифест плагина
├── AGENTS.md            # Шпаргалка для AI-ассистентов
├── ARCHITECTURE.md      # Архитектура плагина
├── README.md            ← этот файл
├── pyproject.toml       # Ruff-линтер конфиг
├── .github/workflows/   # CI (ruff + bandit + pytest)
├── agents/
│   ├── architect.prompt    # Промпт для @architect
│   ├── researcher.prompt   # Промпт для @researcher
│   ├── reviewer.prompt     # Промпт для @reviewer
│   └── security.prompt     # Промпт для @security
└── tests/
    ├── test_classify.py  # 16 тестов для классификации
    └── test_state.py     # 8 тестов для state persistence
```

### Безопасность

- **Path traversal protection** — `handle_prompt()` проверяет, что файл агента лежит внутри `agents/`
- **Нет хардкоженных ключей** — все credentials через Hermes credential pool
- **No shell injection** — `exec.Command` с `shell=false` (утром Go-стиль)
- **CI quality gates** — ruff (линтер) + bandit (SAST) + pytest перед каждым мержем
- **state.json** — живёт локально в директории плагина, не в git

### License

MIT

---

## Development

```bash
# Установка зависимостей
pip install pytest ruff bandit

# Запуск тестов
python -m pytest tests/ -q -v

# Линтер
ruff check .

# SAST
bandit -r . -ll -q
```
