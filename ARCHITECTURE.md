# Pipeline Plugin — Architecture

## Purpose

Плагин-оркестратор для Hermes Agent, реализующий multi-agent пайплайны с quality gates.
Задача: автоматизировать сложные задачи (новые фичи, багфиксы, рефакторинг) через
последовательность специализированных агентов с разными моделями.

## Key Design Decisions

1. **Плагин, не MCP-сервер** — работает in-process с доступом к Hermes API и состоянию.
2. **Нет команд** — пайплайн запускается не по команде, а по анализу сообщения агентом.
3. **Состояние на диске** — JSON-файл для возобновления после перезапуска сессии.
4. **Три уровня моделей** — Flash для быстрых задач, Pro (через delegation) для точных,
   OpenRouter free для редких и нетяжёлых.
5. **Я — оркестратор** — плагин только даёт инструменты (классификация, промпты, модель,
   состояние). Логику пайплайна и вызовы делаю я, а не плагин.

## Architecture

```
┌─ User ─────────────────────┐
│ "добавь JWT аутентификацию" │
└────────────┬────────────────┘
             │ я анализирую ключевые слова
             ▼
┌─ Agent (я, DeepSeek V4 Flash) ─────────────────────┐
│                                                      │
│  1. Распознаю триггер → вызываю pipeline_classify()  │
│  2. Категоризирую → строю pipeline                   │
│  3. checkpoint → спрашиваю тебя                      │
│  4. Выполняю фазу:                                   │
│     ├─ простые агенты → делаю сам (Flash)            │
│     ├─ architect/reviewer/security → delegate_task    │
│     │  (авто V4 Pro через твой delegation)           │
│     └─ researcher → delegate_task с OpenRouter free  │
│  5. Сохраняю состояние → pipeline_save()             │
│  6. checkpoint → спрашиваю тебя                      │
│  ...повторяю до конца пайплайна                      │
│  7. Очищаю состояние → pipeline_clear()              │
└──────────────────────────────────────────────────────┘
             │
             ▼
┌─ Pipeline Plugin ─────────────────────────────────────┐
│                                                        │
│  pipeline_classify(request) → {category, pipeline[]}   │
│  pipeline_save(state) → сохраняет state.json           │
│  pipeline_load() → загружает state.json                │
│  pipeline_clear() → удаляет state.json                 │
│  agent_prompt(agent_id, context) → собирает промпт     │
│  agent_model(agent_id) → {provider, model}             │
│                                                        │
│  ┌─── classify.py ────────────────────┐                │
│  │  keyword-based категоризация       │                │
│  │  8 категорий + pipelines           │                │
│  └────────────────────────────────────┘                │
│  ┌─── state.py ───────────────────────┐                │
│  │  lifecycle: running / paused / done │                │
│  │  expiry: 24h                       │                │
│  └────────────────────────────────────┘                │
│  ┌─── agents/ ────────────────────────┐                │
│  │  architect.prompt                  │                │
│  │  reviewer.prompt                   │                │
│  │  security.prompt                   │                │
│  │  researcher.prompt                 │                │
│  └────────────────────────────────────┘                │
└────────────────────────────────────────────────────────┘
```

## Pipeline Definitions

| Category | Pipeline |
|----------|----------|
| FEATURE | finder → analyst → architect → planner → coder → reviewer → tester → documenter |
| SECURITY_RELATED | finder → analyst → researcher → architect → planner → coder → reviewer → security → tester → documenter |
| BUG_UNKNOWN | finder → debugger → fixer → reviewer → tester |
| BUG_KNOWN | finder → fixer → reviewer → tester |
| REFACTORING | finder → analyst → refactorer → reviewer → tester |
| PERFORMANCE | finder → analyst → optimizer → reviewer → tester |
| INFRASTRUCTURE | finder → devops → (reviewer → tester if testable) |
| DOCUMENTATION | finder → documenter → (reviewer optional) |

## Model Routing

| Agent | Executor | Model |
|-------|----------|-------|
| @finder, @analyst, @planner | Я напрямую | DeepSeek V4 Flash |
| @coder, @editor, @fixer, @refactorer | Я напрямую | DeepSeek V4 Flash |
| @tester, @debugger | Я напрямую | DeepSeek V4 Flash |
| @documenter, @devops, @optimizer | Я напрямую | DeepSeek V4 Flash |
| @architect | delegate_task | DeepSeek V4 Pro (твой delegation) |
| @reviewer | delegate_task | DeepSeek V4 Pro |
| @security | delegate_task | DeepSeek V4 Pro |
| @researcher | delegate_task | OpenRouter free (openrouter/free) |
| @commenter | delegate_task | OpenRouter free |

## State Schema

Хранится в `~/.hermes/plugins/pipeline/state.json`:

```
{
  "request": "string",
  "category": "string",
  "pipeline": ["finder", ...],
  "current_idx": 0,
  "completed": ["finder"],
  "context": {
    "research": { ... },
    "planning": { ... },
    "implementation": { ... },
    "quality": { ... },
    "documentation": { ... }
  },
  "checkpoints": {
    "research_approved": bool | null,
    "plan_approved": bool | null,
    "implementation_approved": bool | null
  },
  "created_at": "ISO",
  "updated_at": "ISO",
  "status": "running" | "paused" | "done"
}
```

## Quality Gates

- **@reviewer** — после любого изменения кода. Если FAIL → revision loop до 3
- **@tester** — после любого изменения кода. Если FAIL → @fixer → retest
- **@security** — для SECURITY_RELATED. Если FAIL → STOP, показать пользователю
- Revision loop: максимум 3 итерации, потом escalation к пользователю

## Files

```
hermes-pipeline-plugin/
├── ARCHITECTURE.md            ← этот файл
├── AGENTS.md                  ← инструкции для агентов
├── README.md                  ← общее описание
├── plugin.yaml                ← манифест плагина Hermes
├── __init__.py                ← ядро плагина
├── classify.py                ← классификация запросов
├── state.py                   ← управление состоянием
├── agents/
│   ├── architect.prompt
│   ├── reviewer.prompt
│   ├── security.prompt
│   └── researcher.prompt
├── skill/
│   └── pipeline-orchestrator/
│       ├── SKILL.md                    ← оркестратор (checkpoints, revision loops)
│       ├── references/
│       │   ├── go-security-tools.md    ← установка gosec/gitleaks
│       │   └── pipeline_lessons.md     ← реальные gotcha
│       └── scripts/
│           └── go-quality-gates.sh     ← скрипт проверки качества
├── references/                ← резервировано
├── .cursor/backlog/
│   ├── each-step-log.mdc      ← per-turn лог
│   └── significant-changes-summary.mdc  ← сводка
├── pyproject.toml             ← ruff config + build system
├── LICENSE                    ← MIT
└── state.json                 ← runtime state (gitignored)
```

## Изменения

| Дата | Что |
|------|-----|
| 2026-07-18 | Начальная архитектура |
| 2026-07-18 | Security audit: path traversal fix, state error handling |
| 2026-07-18 | Full refactoring + documentation + public release |
