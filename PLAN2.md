# PLAN2 — `pipeline_run_agent` API & All Changes

**Проблема:** `delegate_task` — agent-level инструмент, плагин не может его вызвать.
Сейчас в скилле оркестратора написано «вызываю delegate_task для Pro-агентов», но это невозможно
изнутри плагина. Решение: `pipeline_run_agent` возвращает **delegation package** — структуру,
которую оркестратор читает и сам вызывает `delegate_task`.

**Scope:** +1 инструмент (10-й), правки в `__init__.py`, скилл, `AGENTS.md`, `ARCHITECTURE.md`,
`kanban.py` (минимально), `plugin.yaml`.

---

## 1. API: `pipeline_run_agent(state, agent_id, context?)`

### 1.1 Schema (JSON Schema)

```json
{
  "name": "pipeline_run_agent",
  "description": "Build a delegation package for running a pipeline agent. Returns prompt, model routing, and a directive telling the orchestrator how to execute the agent (delegate_task for Pro agents, direct execution for Flash agents). The orchestrator reads the response and calls delegate_task or executes directly.",
  "parameters": {
    "type": "object",
    "properties": {
      "state": {
        "type": "object",
        "description": "Current pipeline state (from pipeline_load/resume). Must contain request, pipeline, current_idx, etc."
      },
      "agent_id": {
        "type": "string",
        "description": "Agent to run: architect, reviewer, security, integration, coder, tester, etc."
      },
      "context": {
        "type": "object",
        "description": "Optional context override. If omitted, uses state.context if available."
      }
    },
    "required": ["state", "agent_id"]
  }
}
```

### 1.2 Return Format (delegation package)

```json
{
  "agent_id": "architect",
  "directive": "delegate",
  "tool_hint": "delegate_task",
  "provider": "delegate",
  "model": "deepseek-v4-pro",
  "prompt": "You are the @architect for the pipeline...",
  "call_args": {
    "prompt": "<full built prompt>",
    "provider": "delegate",
    "model": "deepseek-v4-pro",
    "description": "Pipeline agent: architect"
  },
  "state": {
    "request": "...",
    "category": "FEATURE",
    "pipeline": ["finder", "analyst", "architect", ...],
    "current_idx": 2,
    "completed": ["finder", "analyst"],
    "kanban_parent_id": "abc123",
    "kanban_task_ids": {"finder": "x", "analyst": "y", ...},
    "status": "running"
  }
}
```

**Directive semantics:**

| `directive` | Meaning | `tool_hint` | What orchestrator does |
|-------------|---------|-------------|------------------------|
| `"delegate"` | Pro agent (architect, reviewer, security, integration) | `"delegate_task"` | Calls `delegate_task(**call_args)`, captures result |
| `"delegate_free"` | Free-tier agent (researcher, commenter) | `"delegate_task"` | Calls `delegate_task(**call_args)`, model/provider from call_args |
| `"direct"` | Flash agent (coder, tester, finder, etc.) | `null` | Uses prompt directly in own context — no subprocess delegation |

### 1.3 Error Handling

| Condition | Return |
|-----------|--------|
| Unknown agent_id | `{"error": "Unknown agent: <agent_id>"}` |
| state missing `request` | `{"error": "State missing required field: request"}` |
| state missing `pipeline` | `{"error": "State missing required field: pipeline"}` |
| Prompt template file not found | `{"error": "Prompt template not found: agents/<agent_id>.prompt"}` |
| Template format error (KeyError) | `{"error": "Missing placeholder in prompt: <key>"}` |

### 1.4 Handler Logic (pseudocode)

```python
def handle_run_agent(args, **kwargs):
    agent_id = args["agent_id"]
    state = args["state"]
    context_override = args.get("context")

    # 1. Validate state
    if "request" not in state:
        return error("State missing required field: request")
    if "pipeline" not in state:
        return error("State missing required field: pipeline")

    # 2. Validate agent_id
    agent_id = os.path.basename(agent_id)  # path traversal guard
    routing = MODEL_MAP.get(agent_id)
    if routing is None:
        return error(f"Unknown agent: {agent_id}")

    # 3. Resolve context
    ctx = context_override or state.get("context", {})
    request = state.get("request", "")
    category = state.get("category", "")

    # 4. Build prompt (same logic as handle_prompt)
    prompt_path = os.path.join(PLUGIN_DIR, "agents", f"{agent_id}.prompt")
    if not os.path.exists(prompt_path):
        return error(f"Prompt template not found: agents/{agent_id}.prompt")

    with open(prompt_path, "r") as f:
        template = f.read()

    request_esc = request.replace("{", "{{").replace("}", "}}")
    category_esc = category.replace("{", "{{").replace("}", "}}")

    prompt = template.format(
        request=request_esc,
        category=category_esc,
        research_context=json.dumps(ctx.get("research", {}), ...),
        planning_context=json.dumps(ctx.get("planning", {}), ...),
        implementation_context=json.dumps(ctx.get("implementation", {}), ...),
        quality_context=json.dumps(ctx.get("quality", {}), ...),
        documentation_context=json.dumps(ctx.get("documentation", {}), ...),
        infrastructure_context=json.dumps(ctx.get("infrastructure", {}), ...),
        full_context=json.dumps(ctx, ...),
    )

    # 5. Determine directive
    provider = routing["provider"]
    model = routing["model"]

    if provider in ("delegate",):
        directive = "delegate"
        tool_hint = "delegate_task"
    elif provider in ("delegate_free",):
        directive = "delegate_free"
        tool_hint = "delegate_task"
    else:  # "direct"
        directive = "direct"
        tool_hint = None

    # 6. Build call_args for delegation
    call_args = None
    if directive in ("delegate", "delegate_free"):
        call_args = {
            "prompt": prompt,
            "provider": provider,
            "model": model,
            "description": f"Pipeline agent: {agent_id}",
        }

    # 7. Return delegation package
    return json.dumps({
        "agent_id": agent_id,
        "directive": directive,
        "tool_hint": tool_hint,
        "provider": provider,
        "model": model,
        "prompt": prompt,
        "call_args": call_args,
        "state": state,  # pass-through for pipeline_advance
    }, ensure_ascii=False)
```

---

## 2. Изменения в скилл `pipeline-orchestrator`

### 2.1 Добавить: «Delegation Rule» (перед «Available Tools»)

```markdown
## 🚨 Delegation Rule (CRITICAL)

`delegate_task` — это **agent-level** инструмент. Плагин НЕ МОЖЕТ его вызвать.
Вместо этого используй `pipeline_run_agent(state, agent_id)`:

1. Вызови `pipeline_run_agent(state, agent_id)` → получи delegation package
2. Прочитай `call_args` из ответа
3. Вызови `delegate_task(**call_args)` сам (ты — оркестратор, а не плагин)
4. Сохрани результат
5. Вызови `pipeline_advance(state, agent_id)` → promote следующего

**Никогда не пытайся вызвать delegate_task изнутри плагина.**
**Всегда: pipeline_run_agent → delegate_task → pipeline_advance.**
```

### 2.2 Обновить «Pipeline Flow» (заменить «run_agent» блок)

```markdown
3. Цикл по агентам:
   for each agent_id in pipeline[current_idx:]:
     # ── Шаг 1: получи delegation package ──
     pkg = pipeline_run_agent(state, agent_id)
     # pkg = {agent_id, directive, tool_hint, provider, model, prompt, call_args, state}

     # ── Шаг 2: выполни агента ──
     if pkg.directive == "delegate" or pkg.directive == "delegate_free":
       result = delegate_task(**pkg.call_args)
       # сохрани result
     elif pkg.directive == "direct":
       # используй pkg.prompt напрямую в своём контексте (Flash-агенты)
       # выполняй шаги промпта своими инструментами
       result = <твой вывод после выполнения>

     # ── Шаг 3: продвинь пайплайн ──
     state = pipeline_advance(pkg.state, agent_id)
     # state.current_idx теперь указывает на следующего агента

     # ── Шаг 4: checkpoint? ──
     # Спроси пользователя на ключевых этапах
```

### 2.3 Обновить «Available Tools» (таблица +10-й инструмент)

```markdown
| 10 | `pipeline_run_agent(state, agent_id, context?)` | Build delegation package: prompt + routing + directive |
```

### 2.4 Обновить «Convergence round» блок

```markdown
4. Конвергенция (после @tester + @documenter):
   findings = собрать из результатов ревью/секьюрити
   decision = pipeline_convergence(state, findings)
   → continue? → раунд 2:
       1. pipeline_run_agent(state, "coder") → pkg
       2. delegate_task(**pkg.call_args)
       3. Затем reviewer → security → integration → tester → documenter
       4. (каждый через pipeline_run_agent → delegate_task → pipeline_advance)
   → converged? → готово, pipeline_clear()
   → stuck? → показать findings, спросить что делать
```

---

## 3. Изменения в `__init__.py`

### 3.1 Добавить `RUN_AGENT_SCHEMA` (после MODEL_SCHEMA, строка 198)

```python
RUN_AGENT_SCHEMA = {
    "name": "pipeline_run_agent",
    "description": (
        "Build a delegation package for running a pipeline agent. "
        "The orchestrator reads the response and calls delegate_task (for Pro agents) "
        "or executes the prompt directly (for Flash agents). "
        "Returns {agent_id, directive, tool_hint, provider, model, prompt, call_args, state}."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "state": {
                "type": "object",
                "description": "Current pipeline state (from pipeline_load/resume).",
            },
            "agent_id": {
                "type": "string",
                "description": "Agent to run: architect, reviewer, security, coder, etc.",
            },
            "context": {
                "type": "object",
                "description": "Optional context override. Uses state.context if omitted.",
            },
        },
        "required": ["state", "agent_id"],
    },
}
```

### 3.2 Добавить `handle_run_agent` (после handle_model, строка 359)

Полный код как в §1.4.

### 3.3 Обновить `register()` — добавить 10-й инструмент

```python
def register(ctx):
    for name, schema, handler in [
        ("pipeline_classify", CLASSIFY_SCHEMA, handle_classify),
        ("pipeline_convergence", CONVERGENCE_SCHEMA, handle_convergence),
        ("pipeline_save", SAVE_SCHEMA, handle_save),
        ("pipeline_load", LOAD_SCHEMA, handle_load),
        ("pipeline_clear", CLEAR_SCHEMA, handle_clear),
        ("pipeline_resume", RESUME_SCHEMA, handle_resume),
        ("pipeline_advance", ADVANCE_SCHEMA, handle_advance),
        ("agent_prompt", PROMPT_SCHEMA, handle_prompt),
        ("agent_model", MODEL_SCHEMA, handle_model),
        ("pipeline_run_agent", RUN_AGENT_SCHEMA, handle_run_agent),  # ← NEW
    ]:
        ctx.register_tool(name=name, toolset="pipeline", schema=schema, handler=handler)
```

### 3.4 Обновить docstring модуля

```
Provides 10 tools:
  ...
  - pipeline_run_agent: build delegation package for an agent (10th, v2.1)
```

---

## 4. Изменения в `kanban.py`

### 4.1 Минимальные — добавить хелпер `get_agent_context(state)` (опционально)

Полезная вспомогательная функция для извлечения контекста из state,
но не критична — `hande_run_agent` может работать с `state.get("context", {})`.

```python
def get_agent_context(state: dict, agent_id: str) -> dict:
    """Extract agent-specific context from pipeline state.

    Returns context dict with agent-appropriate sections
    (e.g. @coder gets implementation_context, @reviewer gets quality_context).
    """
    ctx = state.get("context", {})

    # Build agent-specific context
    agent_ctx = dict(ctx)  # shallow copy
    # Highlight the most relevant section
    if agent_id in ("coder", "editor", "fixer", "refactorer"):
        agent_ctx["_focus"] = "implementation"
    elif agent_id in ("reviewer", "security", "tester"):
        agent_ctx["_focus"] = "quality"
    elif agent_id == "documenter":
        agent_ctx["_focus"] = "documentation"
    elif agent_id == "devops":
        agent_ctx["_focus"] = "infrastructure"

    return agent_ctx
```

**Статус:** опционально, можно отложить на v2.2. Не блокирует v2.1.

---

## 5. Изменения в `AGENTS.md`

### 5.1 Обновить Tools таблицу — +1 строка

```markdown
| `pipeline_run_agent(state, agent_id, context?)` | Build delegation package — returns prompt, model routing, and directive |
```

### 5.2 Обновить Model Routing секцию — добавить Delegation Package note

```markdown
## Model Routing & Delegation Package

Агенты делятся на три типа по `directive`, возвращаемому `pipeline_run_agent()`:

- **`directive: "delegate"`** → Pro (architect, reviewer, security, integration)
  Оркестратор вызывает `delegate_task(**call_args)` и получает результат.
- **`directive: "delegate_free"`** → Free-tier (researcher, commenter)
  Аналогично delegate, но через OpenRouter free модели.
- **`directive: "direct"`** → Flash (finder, analyst, planner, coder, editor, fixer,
  refactorer, tester, debugger, documenter, devops, optimizer)
  Оркестратор использует prompt напрямую в своём контексте.

Никогда не вызывай delegate_task напрямую — всегда через pipeline_run_agent.
```

### 5.3 Обновить заголовок «Tools (v2.0)» → «Tools (v2.1)»

### 5.4 Обновить «v1.x → v2.0 Changes» → добавить v2.1

```markdown
| 9 tools | **10 tools** (+ pipeline_run_agent) |
```

---

## 6. Изменения в `ARCHITECTURE.md`

### 6.1 Обновить диаграмму — добавить pipeline_run_agent

```
│  4. Цикл по агентам:                                  │
│     ├─ pipeline_run_agent(state, agent) → pkg          │  ← NEW
│     ├─ delegate_task(**pkg.call_args)  (для Pro)       │  ← оркестратор сам
│     ├─ или выполняю prompt напрямую    (для Flash)      │
│     └─ pipeline_advance(state, agent) → promote next   │
```

### 6.2 Обновить секцию «Pipeline Plugin (9 tools)» → «(10 tools)»

```markdown
┌─ Pipeline Plugin (10 tools) ───────────────────────────┐
│  pipeline_run_agent(s, a, c) → delegation package       │  ← NEW
│  ...остальные 9 инструментов...                         │
```

### 6.3 Обновить таблицу «Изменения» — добавить строку

```markdown
| 2026-07-19 | **v2.1.0**: +pipeline_run_agent (delegation package pattern), 10 tools |
```

---

## 7. Изменения в `plugin.yaml`

```yaml
name: pipeline
version: 2.1.0
description: "Pipeline Plugin v2.1 Kanban-native. Variant C: kanban.db is SSOT. 10 tools: +pipeline_run_agent (delegation package)."
provides_tools:
  - pipeline_classify
  - pipeline_convergence
  - pipeline_save
  - pipeline_load
  - pipeline_clear
  - pipeline_resume
  - pipeline_advance
  - agent_prompt
  - agent_model
  - pipeline_run_agent        # ← NEW (10th)
```

---

## 8. Порядок реализации

| # | Файл | Что | Зависит от |
|---|------|-----|-----------|
| 1 | `__init__.py` | +RUN_AGENT_SCHEMA, +handle_run_agent, +register entry | — |
| 2 | `plugin.yaml` | bump 2.0.0 → 2.1.0, +pipeline_run_agent | 1 |
| 3 | `AGENTS.md` | Обновить таблицу, model routing, version | 2 |
| 4 | `ARCHITECTURE.md` | Обновить диаграмму, tools, changelog | 2 |
| 5 | `skill/pipeline-orchestrator/SKILL.md` | Delegation Rule, Pipeline Flow, таблица | 2 |
| 6 | `kanban.py` | (опционально) get_agent_context helper | — |
| 7 | Тесты | `test_init.py` + новый test для run_agent | 1 |

### Pitfalls при реализации

1. **Stale code после правки.** Плагин грузится при старте сессии. После `patch` на
   `__init__.py` нужен рестарт Hermes-сессии (новый чат). `hermes plugins reload` не
   перезагружает Python-модули полностью.

2. **Экранирование `{}` в промптах.** `handle_run_agent` должен экранировать request и
   category перед `.format()`, так же как `handle_prompt`. Не забыть.

3. **Path traversal guard.** `agent_id` передаётся как часть пути к файлу. Нужна
   проверка через `os.path.basename()` + `os.path.realpath()` как в `handle_prompt`.

4. **call_args = null для direct.** Оркестратор не должен пытаться вызвать
   `delegate_task` если `call_args` is None. Проверить условие в скилле.

5. **Скилл в двух местах.** Скилл лежит в репозитории
   (`skill/pipeline-orchestrator/SKILL.md`) и симлинком в
   `~/.hermes/skills/hermes/pipeline-orchestrator/SKILL.md`. Править нужно файл в
   репозитории (симлинк подхватит).

---

## 9. Проверка (после реализации)

```bash
# 1. Линтер
cd ~/git/hermes-pipeline-plugin
ruff check __init__.py kanban.py

# 2. Синтаксис
python3 -c "import ast; ast.parse(open('__init__.py').read()); print('OK')"

# 3. Тесты (если есть в CI, локально может не хватать hermes-agent)
make test || echo "CI-only: requires hermes-agent runtime"

# 4. YAML валидация
python3 -c "import yaml; yaml.safe_load(open('plugin.yaml')); print('OK')"

# 5. Проверить что все 10 tools в plugin.yaml матчатся с register()
grep -c 'provides_tools' plugin.yaml   # должно быть 10
grep -c 'register_tool' __init__.py    # должно быть 10
```
