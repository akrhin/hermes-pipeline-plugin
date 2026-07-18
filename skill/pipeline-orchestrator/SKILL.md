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
| `"delegate_specific"` | Call `delegate_task` with explicit model pinning |

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

**@reviewer — always after code changes**

```python
reviewer_results = run_agent_pro("reviewer", "Review the implemented code", context)
context["quality"]["reviewer"] = reviewer_results
save_state()

# If reviewer returned NEEDS_REVISION:
for attempt in range(3):  # max 3 iterations
    fixer_results = run_agent("fixer", f"Fix these issues: {reviewer_issues}")
    context["quality"]["fixer"] = fixer_results
    reviewer_results = run_agent_pro("reviewer", "Verify fixes", context)
    context["quality"]["reviewer"] = reviewer_results
    save_state()
    if reviewer_results.status == "PASS":
        break
# If still FAIL after 3 → escalate to user
```

**@security — if SECURITY_RELATED and AFTER reviewer**

```python
security_results = run_agent_pro("security", "Audit code for vulnerabilities", context)
context["quality"]["security"] = security_results
save_state()

# If security FAILS with critical/high:
# STOP pipeline, show user, do not continue until resolved
if security_results.get("blocked"):
    show_to_user("⚠️ Security found critical issues. Pipeline stopped.")
    return
```

**@tester — always after code changes, AFTER reviewer/security**

```python
tester_results = run_agent("tester", "Write and run tests", context)
context["quality"]["tester"] = tester_results
save_state()

# If tests fail:
for attempt in range(3):
    fixer_results = run_agent("fixer", f"Fix failing tests: {test_failures}")
    tester_results = run_agent("tester", "Re-run tests", context)
    if tester_results.status == "PASS":
        break
```

**No checkpoint here** — quality gates are automated. Only interrupt on critical security failures.

Show results:

```
✅ Quality gates:
- @reviewer: PASS (2 nits)
- @security: PASS (0 findings)
- @tester: 12/12 tests passed, 85% coverage
```

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
