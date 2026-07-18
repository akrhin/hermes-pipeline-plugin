---
name: pipeline-orchestrator
description: Orchestration logic for Pipeline Plugin — how to classify, run checkpoints, delegate agents, handle revision loops, and resume state.
version: 1.0.0
author: akrhin
category: hermes
tags: [pipeline, orchestration, multi-agent, quality-gates]
---

# Pipeline Orchestrator

## When to Load

1. User sends a complex task that involves auth/security, a new feature, a bug fix, refactoring, or performance — anything that could benefit from quality gates
2. A `state.json` exists in `~/.hermes/plugins/pipeline/state.json` — resume context

## Trigger Detection

Analyze the user's message for keywords. No special commands needed — the agent decides:

| Keyword / phrase | Action |
|----------------|--------|
| `auth`, `jwt`, `token`, `password`, `secret`, `security`, `безопасност` | Classify as SECURITY_RELATED |
| `bug`, `crash`, `баг`, `пада`, `сломал`, `ошибк` | Classify as BUG_UNKNOWN |
| `fix`, `исправ`, `почини` | Classify as BUG_KNOWN |
| `refactor`, `рефакторинг`, `перепиш`, `передела` | Classify as REFACTORING |
| `optimize`, `slow`, `memory`, `оптимизир`, `тормоз` | Classify as PERFORMANCE |
| `docker`, `deploy`, `config`, `devops`, `инфраструктур` | Classify as INFRASTRUCTURE |
| `docs`, `readme`, `документац`, `описани` | Classify as DOCUMENTATION |
| Everything else with complexity | Classify as FEATURE |
| `да`, `yes`, `продолжаем` after checkpoint | Proceed to next phase |
| `стоп`, `нет`, `хватит`, `отмена` after checkpoint | Abort or show details |
| "статус", "что в пайплайне", "на каком этапе" | Show pipeline status |

If the message is a simple request — handle normally without pipeline.

## How to Classify a Request

```python
from hermes_tools import tool_call

# Step 1: classify the request
classification = tool_call("pipeline_classify", {"request": user_request})
# Returns: {"category": "SECURITY_RELATED", "pipeline": ["finder", "analyst", ...]}
```

After classification, **show the user what was detected**:

```
📋 Классификация: SECURITY_RELATED
Пайплайн: @finder → @analyst → @researcher → @architect → @planner → @coder → @reviewer → @security → @tester → @documenter
Запускаю research...
```

## How to Get Model for an Agent

```python
model_info = tool_call("agent_model", {"agent_id": "architect"})
# Returns: {"provider": "delegate", "model": "deepseek-v4-pro"}
```

Three provider types:

| provider value | What the agent does |
|----------------|---------------------|
| `"direct"` | Handle the agent's work yourself (your own model) |
| `"delegate"` | Call `delegate_task(goal=..., context=...)` |
| `"delegate_free"` | Pass `"openrouter/free"` in the delegation context |

## How to Build Agent Prompts

```python
prompt_result = tool_call("agent_prompt", {
    "agent_id": "architect",
    "context": current_context,     # The accumulated pipeline context object
    "request": original_request,
    "category": category,
})
prompt = prompt_result["prompt"]
```

## Pipeline Lifecycle

### Phase Structure

Each pipeline follows this pattern:

```
Phase 1: RESEARCH  ── @finder, @analyst, (@researcher)
                      ↓ checkpoint: "Research complete. Continue?"
Phase 2: PLANNING  ── @architect, @planner
                      ↓ checkpoint: "Plan ready. Start implementation?"
Phase 3: IMPLEMENT  ── @coder (or @editor/@fixer/@refactorer)
                      ↓ checkpoint: "Code written. Run quality gates?"
Phase 4: QUALITY   ── @reviewer, (@security), @tester
                      ↓ no checkpoint (auto resolve)
Phase 5: DOCS      ── @documenter (@commenter)
                      ↓ checkpoint: "Pipeline complete!"
```

### Phase Execution Detail

#### Phase 1: Research

Run agents sequentially. Store results in `context.research`.

```python
# @finder — always first
finder_results = run_agent("finder", "Search the codebase for relevant files, patterns, and project structure")

# @analyst — if pipeline has it
analyst_results = run_agent("analyst", "Analyze dependencies, risks, data flow")

# @researcher — if pipeline has it (typically for security or new libraries)
researcher_results = run_agent_free("researcher", "Find best practices, documentation, and solutions")

# Save context
context["research"] = {"finder": finder_results, "analyst": analyst_results, "researcher": researcher_results}
save_state()
```

Present checkpoint:

```
📋 Research complete:
- Найдено файлов: 3 (auth.go, middleware/auth.go, config.go)
- Стек: Go 1.22, gin, golang-jwt v5
- Риски: нет refresh token rotation
- Best practices: OWASP JWT Cheatsheet

Продолжаем? [да / план / стоп]
```

#### Phase 2: Planning

```python
architect_results = run_agent_delegate("architect", "Design solution architecture", context)
planner_results = run_agent("planner", "Decompose into atomic tasks")

context["planning"] = {"architect": architect_results, "planner": planner_results}
save_state()
```

Present checkpoint:

```
📋 План:
1. Создать auth/jwt.go — генерация и валидация токенов
2. Создать middleware/auth.go — middleware для gin
3. Обновить config.go — добавить JWT_SECRET, TOKEN_TTL
4. Обновить router.go — подключить middleware

Изменяемые файлы: auth/jwt.go, middleware/auth.go, config.go, router.go
Сложность: средняя

Начинаем реализацию? [да / изменить план / стоп]
```

#### Phase 3: Implementation

```python
coder_results = run_agent("coder", f"Implement according to the plan")
# Note: for bugfixes use @fixer, for refactoring use @refactorer, etc.

# Determine which implementation agent based on category:
# FEATURE/SECURITY → coder
# BUG_KNOWN/BUG_UNKNOWN → fixer
# REFACTORING → refactorer
# PERFORMANCE → optimizer
# INFRASTRUCTURE → devops

context["implementation"] = {"coder": coder_results}
save_state()
```

Present checkpoint only if user said yes to continue — otherwise wait for confirmation first.

#### Phase 4: Quality Gates

Принципиальное отличие от старой версии: пайплайн — это **когерентный цикл с конвергенцией**, а не линейный конвейер. 

Вместо одного прохода coder→reviewer:

```
coder → (reviewer + security + tester) → 
    ├── P0/P1 findings = 0 → ГОТОВО (converged)
    ├── same findings 2× → STUCK (escalation)
    ├── max 3 раунда → MAXED_OUT (forced stop)
    └── есть новые findings → coder с фидбеком (continue)
```

### Инструмент конвергенции

```python
# После quality gates — оценить конвергенцию
result = tool_call("pipeline_convergence", {
    "findings": [
        {"severity": "P0", "file": "auth.go", "category": "security", 
         "description": "XSS в логине"},
        {"severity": "P1", "file": "config.go", "category": "error_handling",
         "description": "Нет проверки пустого secret"},
        {"severity": "P2", "file": "main.go", "category": "style",
         "description": "Длинная строка (120 > 100)"},
    ]
})
# Returns:
# {"decision": "continue", "reason": "2 P0/P1 findings remain — round 2/3",
#  "round": 1, "p0_count": 1, "p1_count": 1, "p2_count": 1}
```

**4 возможных решения:**

| decision | Что значит | Что делать |
|----------|-----------|------------|
| `continue` | Есть P0/P1, можно ещё round | Вернуть coder с замечаниями |
| `converged` | P0/P1 = 0, можно финишировать | Идти к документер |
| `stuck` | Те же P0/P1 второй раунд | Стоп, escalation к пользователю |
| `maxed_out` | Достигнут max_rounds | Стоп, показать что недоделано |

**Hard stops — в коде, не в промптах.** Max 3 раунда. Fingerprint-сравнение P0/P1. Детерминировано, без LLM.

### Severity (P0/P1/P2)

| Severity | Что это | Действие |
|----------|---------|----------|
| **P0** | Correctness/security — блокирует merge | Обязательно исправить |
| **P1** | Degraded behaviour | Исправить или remediation plan |
| **P2** | Style/naming/minor | Advisory — не блокирует |

#### Phase 5: Documentation

```python
documenter_results = run_agent("documenter", "Write docs for the new code", context)
# Optional: commenter for inline code comments
context["documentation"] = {"documenter": documenter_results}
save_state()
```

Final summary:

```
✅ Пайплайн завершён:
- Категория: SECURITY_RELATED
- Создано: auth/jwt.go, middleware/auth.go
- Изменено: config.go, router.go
- Тесты: 12/12 passed, 85% coverage
- Security: 0 critical, 0 high
- Документация: README обновлён
- Итераций ревью: 2
- Время выполнения: ~3 мин
```

## How to Run Agents

### Run agent directly (provider "direct")

Just handle it yourself — use your own capabilities:

```python
# For @finder: search the codebase
from hermes_tools import search_files
matches = search_files(...)

# For @coder: write the code
from hermes_tools import write_file
write_file(path="new/file.go", content=...)
```

### Run agent via delegate_task (provider "delegate")

```python
from hermes_tools import delegate_task

prompt = tool_call("agent_prompt", {
    "agent_id": "architect",
    "context": context,
    "request": request,
    "category": category,
})["prompt"]

result = delegate_task(
    goal=prompt,
    context=f"Category: {category}\nOriginal request: {request}",
)
```

The agent running the delegate_task will:
- Read files (architect, reviewer, security)
- Review code (reviewer)
- Analyze security (security)

### Run agent via delegate_task with OpenRouter free (provider "delegate_free")

```python
result = delegate_task(
    goal=prompt,
    context=f"Research best practices for: {request}",
)
# The delegate will use openrouter/free
```

Note: `provider "delegate_free"` means the delegate agent will be told to use OpenRouter free model. The agent handles this via context instructions.

## Saving and Loading State

```python
# Save after each phase
from hermes_tools import tool_call
tool_call("pipeline_save", {"state": state_object})

# Load on /resume or at session start
state = tool_call("pipeline_load", {})
if state:
    print(f"📋 Найден незавершённый пайплайн от {state['created_at']}")
    print(f"Статус: {state['status']}, фаза {state['current_idx']}/{len(state['pipeline'])}")
    # Offer to resume

# Clear on completion or /abort
tool_call("pipeline_clear", {})
```

## State Object Structure

Always maintain this shape:

```python
state = {
    "request": "добавь JWT-аутентификацию",
    "category": "SECURITY_RELATED",
    "pipeline": ["finder", "analyst", "researcher", "architect", "planner", "coder", "reviewer", "security", "tester", "documenter"],
    "current_idx": 3,  # 0-based index of next agent to run
    "completed": ["finder", "analyst", "researcher"],
    "context": {
        "research": {},
        "planning": {},
        "implementation": {},
        "quality": {},
        "documentation": {},
    },
    "checkpoints": {
        "research_approved": True,
        "plan_approved": None,
        "implementation_approved": None,
    },
    # ── Convergence fields (auto-managed by pipeline_convergence) ──
    "round": 0,                       # Текущий convergence round
    "max_rounds": 3,                   # Max раундов (hard stop, в коде)
    "findings": [],                    # Список findings с severity/file/category
    "findings_fingerprint": "",        # MD5 P0/P1 findings (последнего раунда)
    "prev_findings_fingerprint": "",   # MD5 P0/P1 findings (предыдущего раунда)
    "convergence": "running",          # running | converged | stuck | maxed_out
    "created_at": "2026-07-18T14:00:00",
    "updated_at": "2026-07-18T14:05:00",
    "status": "running",  # running | paused | done
}
```

## Resume Logic

When `state.json` exists at session start (e.g. after a crash or restart):

```python
state = tool_call("pipeline_load", {})
if not state:
    return  # Nothing to resume

# Show state
print(f"📋 Найден незавершённый пайплайн от {state['created_at']}")
print(f"✅ Завершено: {', '.join(state['completed'])}")
print(f"⏳ Следующий: {state['pipeline'][state['current_idx']]}")
print(f"⚠️ Статус: {state['status']}")

# Ask user
# "Продолжить / сбросить / показать детали?"
```

## Pipeline Phase Summary Table

| Phase | Agents | Checkpoint |
|-------|--------|------------|
| 1. RESEARCH | finder → analyst → (researcher) | ✅ После research: продолжать? |
| 2. PLANNING | architect → planner | ✅ После плана: запускать? |
| 3. IMPLEMENT | coder/editor/fixer/refactorer | ✅ После кода: качество? |
| 4. QUALITY | reviewer → (security) → tester | 🔄 Авто, только критические стоп |
| 5. DOCS | documenter → (commenter) | ✅ Финальный отчёт |

## Model Routing Reference

| Agent | Method | Notes |
|-------|--------|-------|
| @finder | Direct | search_files, read_file, etc. |
| @analyst | Direct | Read + reason |
| @planner | Direct | Read + plan |
| @coder | Direct | write_file, edit |
| @editor | Direct | edit existing files |
| @fixer | Direct | Targeted fixes |
| @refactorer | Direct | Structural changes |
| @tester | Direct | Write + run tests |
| @debugger | Direct | Read + diagnose |
| @documenter | Direct | write_file (docs) |
| @commenter | Direct / delegate_free | Inline comments |
| @devops | Direct | Docker, config, CI |
| @optimizer | Direct | Performance analysis |
| @architect | delegate_task | DeepSeek V4 Pro |
| @reviewer | delegate_task | DeepSeek V4 Pro |
| @security | delegate_task | DeepSeek V4 Pro |
| @researcher | delegate_task | OpenRouter free |

---

## Kanban Dashboard (Hermes Kanban)

Публикует прогресс пайплайна на встроенную Hermes Kanban-доску. База данных — `~/.hermes/kanban.db`, доска `home` по умолчанию.

Никаких внешних сервисов — всё внутри Hermes.

### Архитектура

Hermes Kanban — SQLite-backed доска, встроенная в ядро. Доступна через:

| Интерфейс | Команда |
|-----------|---------|
| **CLI** | `hermes kanban <cmd>` (через `terminal()`) |
| **agent tools** | `kanban_*` (когда toolset `kanban` включён для профиля) |
| **WebUI** | `hermes dashboard` |

**Важно:** `kanban_*` tools в агенте активируются через `toolsets: [kanban]` в профиле. В on-платформенных конфигах (Telegram → `platform_toolsets.telegram`) kanban уже включён. Для CLI-сессии — нет. Поэтому оркестратор использует CLI-команды через `terminal()` — это надёжнее для скриптов.

### Терминология

| Понятие | Описание |
|---------|----------|
| **Board** | Доска (проект / workstream). По умолчанию `home`. |
| **Task** | Единица работы. Статусы: `todo` → `ready` → `running` → `done` / `blocked`. |
| **Status lifecycle** | `todo` (черновик) → `ready` (готов к работе) → `running` (в процессе) → `done`. `blocked` для остановки. `scheduled` для отложенных. `archived` для завершённых. |
| **link** | parent→child зависимость. Ребёнок нельзя промоутить/завершить, пока родитель открыт. |
| **comment** | Запись к таску с деталями прогресса. |
| **workspace** | `scratch` (по умолч.) или `worktree` (клон репо). |

### Как использовать

#### При старте пайплайна

```bash
# Убедиться что доска home активна
hermes kanban boards switch home

# Создать таску на прогон — ready сразу (с --body)
PARENT=$(hermes kanban create --body "Запрос: $REQUEST" --priority 3 --json "🔷 Пайплайн: $REQUEST" | jq -r '.id')
```

#### Создать стадии (все сразу)

```bash
# Каждая стадия — отдельная task. Без --parent чтобы не блокировать
stages=(
  "🔍  finder  аудит кода"
  "📋  analyst  анализ"
  "🔬  researcher  исследование"
  "🏗️  architect  архитектура"
  "📐  planner  план"
  "💻  coder  реализация"
  "👁️  reviewer  ревью"
  "🛡️  security  безопасность"
  "🧪  tester  тесты"
  "📝  documenter  документация"
)

declare -A TASK_IDS
for stage in "${stages[@]}"; do
  read -r emoji agent desc <<< "$stage"
  id=$(hermes kanban create --body "$desc" --priority 1 --json "$emoji @$agent — $desc" | jq -r '.id')
  TASK_IDS[$agent]=$id
done

# Связать последовательно
prev=""
for agent in finder analyst researcher architect planner coder reviewer security tester documenter; do
  if [ -n "$prev" ]; then
    hermes kanban link "${TASK_IDS[$prev]}" "${TASK_IDS[$agent]}"
  fi
  prev=$agent
done
```

#### При завершении стадии

```bash
hermes kanban complete --result "3 findings, converged" "${TASK_IDS[coder]}"
```

#### При блокировке стадии

```bash
hermes kanban block --kind dependency "${TASK_IDS[architect]}" "Missing: API spec from upstream"
```

#### Комментарий с деталями

```bash
hermes kanban comment "${TASK_IDS[analyst]}" "**@analyst** анализ завершён: выявлено 5 классов, 3 security issues"
```

#### При завершении пайплайна

```bash
hermes kanban complete --result "P2 only, converged round 2/3" --summary "Пайплайн выполнен, 12 findings (0 P0, 0 P1, 12 P2)" "$PARENT"
```

#### Просмотр доски

```bash
hermes kanban list
hermes kanban list --status ready
hermes kanban show --json t_XXXXXXXX
hermes kanban stats
```

### Принцип

- Логика дашборда — **в SKILL.md**, не в плагине
- Плагин (`__init__.py`) ничего не знает про Kanban
- Оркестратор (я) сам вызывает `hermes kanban` через `terminal()`
- Kanban — read-only для пользователя: смотреть прогресс, не управлять без причины
- Используя `--body` на create, таск создаётся в статусе `ready` (пропускается `todo`)
- `link` создаёт parent→child: ребёнок не завершится, пока родитель открыт — **не использовать для пайплайна**, только для реальных зависимостей
