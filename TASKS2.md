# TASKS2.md — Атомарные задачи для @coder: `pipeline_run_agent` (v2.0.0 → v2.1.0)

**Source:** PLAN2.md — добавить 10-й инструмент `pipeline_run_agent` (delegation package pattern).

---

## TASK-01: `__init__.py` — добавить `RUN_AGENT_SCHEMA`

**Файл:** `__init__.py`
**Тип:** вставка (после `MODEL_SCHEMA`, текущая строка 198)
**Приоритет:** P0 (блокирует всё остальное)

Вставить после закрывающей `}` схемы `MODEL_SCHEMA` (строка 198) новый блок:

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

---

## TASK-02: `__init__.py` — добавить `handle_run_agent`

**Файл:** `__init__.py`
**Тип:** вставка (после `handle_model`, текущая строка 359)
**Приоритет:** P0

Вставить после закрывающей строки `def handle_model` (строка 359 — последний `return`) новый хендлер:

```python
def handle_run_agent(args, **kwargs):
    """Build delegation package: prompt + routing + directive.
    
    Returns {agent_id, directive, tool_hint, provider, model, prompt, call_args, state}.
    Orchestrator reads call_args and calls delegate_task(**call_args) for Pro agents,
    or uses prompt directly for Flash agents.
    """
    try:
        agent_id = args["agent_id"]
        state = args["state"]
        context_override = args.get("context")

        # 1. Validate state
        if "request" not in state:
            return json.dumps({"error": "State missing required field: request"})
        if "pipeline" not in state:
            return json.dumps({"error": "State missing required field: pipeline"})

        # 2. Validate agent_id (path traversal guard — same as handle_prompt)
        agent_id = os.path.basename(agent_id)
        routing = MODEL_MAP.get(agent_id)
        if routing is None:
            return json.dumps({"error": f"Unknown agent: {agent_id}"})

        # 3. Resolve context
        ctx = context_override if context_override is not None else state.get("context", {})
        request = state.get("request", "")
        category = state.get("category", "")

        # 4. Build prompt from template (same logic as handle_prompt)
        prompt_path = os.path.join(PLUGIN_DIR, "agents", f"{agent_id}.prompt")
        resolved = os.path.realpath(prompt_path)
        agents_dir = os.path.realpath(os.path.join(PLUGIN_DIR, "agents"))
        if not resolved.startswith(agents_dir):
            return json.dumps({"error": f"Prompt template not found: agents/{agent_id}.prompt"})

        with open(resolved, "r", encoding="utf-8") as f:
            template = f.read()

        request_esc = request.replace("{", "{{").replace("}", "}}")
        category_esc = category.replace("{", "{{").replace("}", "}}")

        prompt = template.format(
            request=request_esc,
            category=category_esc,
            research_context=json.dumps(ctx.get("research", {}), ensure_ascii=False, indent=2),
            planning_context=json.dumps(ctx.get("planning", {}), ensure_ascii=False, indent=2),
            implementation_context=json.dumps(ctx.get("implementation", {}), ensure_ascii=False, indent=2),
            quality_context=json.dumps(ctx.get("quality", {}), ensure_ascii=False, indent=2),
            documentation_context=json.dumps(ctx.get("documentation", {}), ensure_ascii=False, indent=2),
            infrastructure_context=json.dumps(ctx.get("infrastructure", {}), ensure_ascii=False, indent=2),
            full_context=json.dumps(ctx, ensure_ascii=False, indent=2),
        )

        # 5. Determine directive
        provider = routing["provider"]
        model = routing["model"]

        if provider == "delegate":
            directive = "delegate"
            tool_hint = "delegate_task"
        elif provider == "delegate_free":
            directive = "delegate_free"
            tool_hint = "delegate_task"
        else:  # "direct"
            directive = "direct"
            tool_hint = None

        # 6. Build call_args for delegation agents
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

    except KeyError as e:
        return json.dumps({"error": f"Missing placeholder in prompt: {e}"})
    except Exception as e:
        return json.dumps({"error": str(e), "traceback": traceback.format_exc()})
```

---

## TASK-03: `__init__.py` — обновить `register()` — добавить 10-й инструмент

**Файл:** `__init__.py`
**Тип:** замена (блок `register()`, строки 365–382)
**Приоритет:** P0

Заменить текущий список туплов в `register()`:

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
        ("pipeline_run_agent", RUN_AGENT_SCHEMA, handle_run_agent),  # ← NEW 10th
    ]:
        ctx.register_tool(
            name=name,
            toolset="pipeline",
            schema=schema,
            handler=handler,
        )
```

---

## TASK-04: `__init__.py` — обновить docstring модуля

**Файл:** `__init__.py`
**Тип:** замена (строки 1–22)
**Приоритет:** P0

Обновить docstring (заменить «v2.0» → «v2.1», «9 tools» → «10 tools», добавить строку про `pipeline_run_agent`):

```python
"""
Pipeline Plugin v2.1 — Kanban-native multi-agent orchestration.

Variant C: state.json eliminated. kanban.db = single source of truth.
Board `pipeline` stores the entire pipeline lifecycle as a task tree.

Provides 10 tools:
  - pipeline_classify: classify request → category + agent list
  - pipeline_convergence: evaluate convergence (deterministic, no LLM)
  - pipeline_save: create/update kanban task tree (idempotent)
  - pipeline_load: reconstruct state from kanban board
  - pipeline_clear: close all kanban tasks (abort/cancel)
  - pipeline_resume: scan board for active pipeline (for restarts)
  - pipeline_advance: mark agent done, promote next
  - agent_prompt: build prompt for a specific agent
  - agent_model: get provider+model for a specific agent
  - pipeline_run_agent: build delegation package for an agent (10th, v2.1)

Key change from v1.x:
  - state.py removed → convergence logic in kanban.py
  - state.json removed → state in kanban.db (Hermes Kanban board)
  - After restart: pipeline_resume() scans board, no state.json needed

Key change from v2.0:
  - pipeline_run_agent added — delegation package pattern (agent→orchestrator bridge)
"""
```

---

## TASK-05: `plugin.yaml` — bump до v2.1.0 + добавить `pipeline_run_agent`

**Файл:** `plugin.yaml`
**Тип:** полная замена
**Приоритет:** P0
**Зависит от:** TASK-01–04 (должны быть выполнены, чтобы plugin.yaml отражал реальность)

```yaml
name: pipeline
version: 2.1.0
description: "Pipeline Plugin v2.1 Kanban-native. Variant C: kanban.db is SSOT. 10 tools: +pipeline_run_agent (delegation package)."
author: Hermes + Vladimir
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
  - pipeline_run_agent
```

---

## TASK-06: `AGENTS.md` — обновить заголовок `Tools (v2.0)` → `Tools (v2.1)`

**Файл:** `AGENTS.md`
**Тип:** замена строки
**Приоритет:** P1
**Зависит от:** TASK-05

Найти: `## Tools (v2.0)`
Заменить на: `## Tools (v2.1)`

Найти: `Плагин регистрирует **9 инструментов**`
Заменить на: `Плагин регистрирует **10 инструментов**`

---

## TASK-07: `AGENTS.md` — добавить строку `pipeline_run_agent` в таблицу Tools

**Файл:** `AGENTS.md`
**Тип:** вставка (после строки `agent_model`, строка ~54)
**Приоритет:** P1
**Зависит от:** TASK-06

После строки таблицы:
```
| `agent_model(agent_id)` | Get provider + model for agent |
```
Вставить:
```
| `pipeline_run_agent(state, agent_id, context?)` | Build delegation package — returns prompt, model routing, and directive |
```

---

## TASK-08: `AGENTS.md` — добавить секцию «Model Routing & Delegation Package»

**Файл:** `AGENTS.md`
**Тип:** вставка (после секции «Model Routing», строка ~62)
**Приоритет:** P1
**Зависит от:** TASK-07

После строки:
```
- **Free** (`delegate_free`, OpenRouter): Researcher, Commenter
```

Вставить:

```markdown

## Delegation Package (via pipeline_run_agent)

`pipeline_run_agent()` возвращает delegation package с полем `directive`:

- **`directive: "delegate"`** → Pro (architect, reviewer, security, integration)
  Оркестратор вызывает `delegate_task(**call_args)` и получает результат.
- **`directive: "delegate_free"`** → Free-tier (researcher, commenter)
  Аналогично delegate, но через OpenRouter free модели.
- **`directive: "direct"`** → Flash (finder, analyst, planner, coder, editor, fixer,
  refactorer, tester, debugger, documenter, devops, optimizer)
  Оркестратор использует prompt напрямую в своём контексте.

**Правило:** никогда не вызывай `delegate_task` напрямую — всегда через `pipeline_run_agent`.
Порядок: `pipeline_run_agent(state, agent_id)` → прочитать `call_args` → `delegate_task(**call_args)` → `pipeline_advance(state, agent_id)`.
```

---

## TASK-09: `AGENTS.md` — обновить «Key Files» и «v1.x → v2.0 Changes»

**Файл:** `AGENTS.md`
**Тип:** замена + вставка
**Приоритет:** P1
**Зависит от:** TASK-08

1. В таблице Key Files строка `plugin.yaml` → заменить на:
```
| `plugin.yaml` | Manifest (v2.1.0, 10 tools) |
```

2. В таблице Key Files строка `__init__.py` → заменить на:
```
| `__init__.py` | Plugin core: 10 tools + register |
```

3. В секции «v1.x → v2.0 Changes», после таблицы (после `| 7 tools | **9 tools** (+ resume + advance) |`), добавить:

```markdown

### v2.0 → v2.1

| Old | New |
|-----|-----|
| 9 tools | **10 tools** (+ pipeline_run_agent) |
| Manual delegation routing in skill | Delegation package returned by plugin |
| Orchestrator guesses delegate vs direct | `directive` field tells orchestrator what to do |
| `agent_prompt` + `agent_model` call separately | `pipeline_run_agent` returns both + call_args |
```

---

## TASK-10: `ARCHITECTURE.md` — обновить заголовок и tools count (9→10)

**Файл:** `ARCHITECTURE.md`
**Тип:** замена строк
**Приоритет:** P1
**Зависит от:** TASK-05

- Найти: `# Pipeline Plugin v2.0 — Architecture` → `# Pipeline Plugin v2.1 — Architecture`
- Найти: `## Key Design Decisions` ... «Три уровня моделей» → добавить упоминание delegation package? — нет, оставить как есть (это остаётся верным).
- Найти: `┌─ Pipeline Plugin (9 tools) ─` → `┌─ Pipeline Plugin (10 tools) ─`
- Найти: `├── ARCHITECTURE.md            ← этот файл (v2.0)` → `├── ARCHITECTURE.md            ← этот файл (v2.1)` 
- Найти: `├── plugin.yaml                ← манифест v2.0.0 (9 tools)` → `├── plugin.yaml                ← манифест v2.1.0 (10 tools)`
- Найти: `├── __init__.py                ← ядро: 9 хендлеров` → `├── __init__.py                ← ядро: 10 хендлеров`

---

## TASK-11: `ARCHITECTURE.md` — обновить диаграмму (добавить pipeline_run_agent)

**Файл:** `ARCHITECTURE.md`
**Тип:** замена блока (строки 31–34, шаг 4 цикла)
**Приоритет:** P1
**Зависит от:** TASK-10

Заменить текущий блок шага 4:
```
│  4. Цикл по агентам:                                  │
│     ├─ pipeline_resume() → беру ready-таск             │
│     ├─ выполняю агента                                 │
│     └─ pipeline_advance(state, agent) → promote next  │
```

На:
```
│  4. Цикл по агентам:                                  │
│     ├─ pipeline_run_agent(state, agent) → pkg          │  ← NEW v2.1
│     ├─ delegate_task(**pkg.call_args)  (для Pro)       │
│     ├─ или выполняю prompt напрямую    (для Flash)      │
│     └─ pipeline_advance(state, agent) → promote next   │
```

И в блоке «Pipeline Plugin (N tools)» (строки 46–54) добавить строку:

После:
```
│  agent_prompt(id, ctx)     → build prompt from template │
│  agent_model(id)           → {provider, model}          │
```

Вставить:
```
│  pipeline_run_agent(s,a,c) → delegation package         │
```

---

## TASK-12: `ARCHITECTURE.md` — добавить строку в таблицу «Изменения»

**Файл:** `ARCHITECTURE.md`
**Тип:** вставка (в конец таблицы «Изменения», строка ~187)
**Приоритет:** P1
**Зависит от:** TASK-11

После строки:
```
|| 2026-07-19 | **Variant C**: state.json → kanban.db SSOT, state.py → kanban.py, +pipeline_resume, +pipeline_advance, 9 tools (v2.0.0) |
```

Вставить:
```
|| 2026-07-19 | **v2.1.0**: +pipeline_run_agent (delegation package pattern), 10 tools |
```

---

## TASK-13: `skill/pipeline-orchestrator/SKILL.md` — обновить заголовок v2.0 → v2.1

**Файл:** `skill/pipeline-orchestrator/SKILL.md`
**Тип:** замена строк
**Приоритет:** P1
**Зависит от:** TASK-05

- YAML frontmatter `description`: `...for Pipeline Plugin v2.0 (Kanban-native)` → `...for Pipeline Plugin v2.1 (Kanban-native)`
- Заголовок: `# Pipeline Orchestrator v2.0` → `# Pipeline Orchestrator v2.1`
- Строка: `Плагин регистрирует **9 инструментов**` → `Плагин регистрирует **10 инструментов**`

---

## TASK-14: `skill/pipeline-orchestrator/SKILL.md` — добавить «Delegation Rule» секцию

**Файл:** `skill/pipeline-orchestrator/SKILL.md`
**Тип:** вставка (перед `## Available Tools`, текущая строка 38)
**Приоритет:** P1
**Зависит от:** TASK-13

Вставить перед `## Available Tools`:

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

---

## TASK-15: `skill/pipeline-orchestrator/SKILL.md` — обновить секцию «Available Tools» — добавить 10-й инструмент

**Файл:** `skill/pipeline-orchestrator/SKILL.md`
**Тип:** вставка (после tool #9, текущая строка 86)
**Приоритет:** P1
**Зависит от:** TASK-14

После блока `### 9. agent_model(agent_id)` вставить:

```markdown
### 10. `pipeline_run_agent(state: dict, agent_id: str, context?: dict)`

Build delegation package for running a pipeline agent. Returns:

```json
{
  "agent_id": "architect",
  "directive": "delegate",
  "tool_hint": "delegate_task",
  "provider": "delegate",
  "model": "deepseek-v4-pro",
  "prompt": "...",
  "call_args": {"prompt": "...", "provider": "delegate", "model": "deepseek-v4-pro", "description": "Pipeline agent: architect"},
  "state": {...}
}
```

**Directive types:**
- `"delegate"` → Pro агенты (architect, reviewer, security, integration). Оркестратор вызывает `delegate_task(**call_args)`.
- `"delegate_free"` → Free-tier (researcher, commenter). Аналогично delegate.
- `"direct"` → Flash-агенты. Оркестратор использует prompt напрямую в своём контексте.
```

---

## TASK-16: `skill/pipeline-orchestrator/SKILL.md` — обновить «Pipeline Flow»

**Файл:** `skill/pipeline-orchestrator/SKILL.md`
**Тип:** замена блока (строки 97–109, шаги 3 и 4)
**Приоритет:** P1
**Зависит от:** TASK-15

Заменить текущий блок:

```
3. Цикл по агентам:
   for each agent in pipeline:
     prompt = agent_prompt(agent, context)
     run_agent(agent, prompt)  ← delegate_task или прямо
     advance(state, agent)     ← mark done, promote next
     checkpoint? ← спросить пользователя

4. Конвергенция (после @tester + @documenter):
   findings = собрать из результатов ревью/секьюрити
   pipeline_convergence({state, findings})
   → continue? → раунд 2 (coder → reviewer → security → tester → documenter)
   → converged? → готово, pipeline_clear()
   → stuck? → показать findings, спросить что делать
```

На:

```
3. Цикл по агентам:
   for each agent_id in pipeline[current_idx:]:
     # ── Шаг 1: получи delegation package ──
     pkg = pipeline_run_agent(state, agent_id)
     # pkg = {agent_id, directive, tool_hint, provider, model, prompt, call_args, state}

     # ── Шаг 2: выполни агента ──
     if pkg.directive in ("delegate", "delegate_free"):
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

## TASK-17: `kanban.py` — добавить хелпер `get_agent_context` (ОПЦИОНАЛЬНО)

**Файл:** `kanban.py`
**Тип:** вставка (в конец файла, перед последней строкой)
**Приоритет:** P2 (опционально, можно отложить на v2.2, НЕ БЛОКИРУЕТ v2.1)

Добавить функцию:

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

---

## TASK-18: `tests/test_init.py` — добавить тесты для `handle_run_agent`

**Файл:** `tests/test_init.py`
**Тип:** вставка (в конец файла)
**Приоритет:** P1
**Зависит от:** TASK-01–04

Добавить тесты для `handle_run_agent`:

```python
# ── pipeline_run_agent tests ───────────────────────────────────────────────

def test_run_agent_returns_delegation_package():
    """handle_run_agent returns full delegation package with expected fields."""
    from __init__ import handle_run_agent
    state = {
        "request": "добавить JWT",
        "category": "FEATURE",
        "pipeline": ["finder", "analyst", "architect"],
        "current_idx": 2,
        "completed": ["finder", "analyst"],
        "status": "running",
    }
    result = json.loads(handle_run_agent({"state": state, "agent_id": "architect"}))
    assert result["agent_id"] == "architect"
    assert result["directive"] == "delegate"
    assert result["tool_hint"] == "delegate_task"
    assert result["provider"] == "delegate"
    assert result["model"] == "deepseek-v4-pro"
    assert "prompt" in result
    assert result["call_args"] is not None
    assert result["call_args"]["prompt"] == result["prompt"]
    assert "state" in result


def test_run_agent_direct_for_flash():
    """Flash agents get directive: 'direct' and call_args: null."""
    from __init__ import handle_run_agent
    state = {
        "request": "test",
        "category": "BUG_KNOWN",
        "pipeline": ["finder", "fixer", "reviewer", "tester"],
        "current_idx": 1,
        "completed": ["finder"],
        "status": "running",
    }
    result = json.loads(handle_run_agent({"state": state, "agent_id": "fixer"}))
    assert result["directive"] == "direct"
    assert result["tool_hint"] is None
    assert result["call_args"] is None


def test_run_agent_delegate_free():
    """Free-tier agents get directive: delegate_free."""
    from __init__ import handle_run_agent
    state = {
        "request": "research",
        "category": "SECURITY_RELATED",
        "pipeline": ["finder", "analyst", "researcher", "architect"],
        "current_idx": 2,
        "completed": ["finder", "analyst"],
        "status": "running",
    }
    result = json.loads(handle_run_agent({"state": state, "agent_id": "researcher"}))
    assert result["directive"] == "delegate_free"
    assert result["tool_hint"] == "delegate_task"
    assert result["call_args"] is not None
    assert result["call_args"]["provider"] == "delegate_free"


def test_run_agent_unknown_agent():
    """Unknown agent_id returns error."""
    from __init__ import handle_run_agent
    state = {"request": "x", "pipeline": ["finder"], "current_idx": 0, "status": "running"}
    result = json.loads(handle_run_agent({"state": state, "agent_id": "nonexistent"}))
    assert "error" in result
    assert "Unknown agent" in result["error"]


def test_run_agent_missing_request():
    """State missing 'request' returns error."""
    from __init__ import handle_run_agent
    state = {"pipeline": ["finder"], "current_idx": 0, "status": "running"}
    result = json.loads(handle_run_agent({"state": state, "agent_id": "finder"}))
    assert "error" in result
    assert "request" in result["error"]


def test_run_agent_missing_pipeline():
    """State missing 'pipeline' returns error."""
    from __init__ import handle_run_agent
    state = {"request": "x", "current_idx": 0, "status": "running"}
    result = json.loads(handle_run_agent({"state": state, "agent_id": "finder"}))
    assert "error" in result
    assert "pipeline" in result["error"]


def test_run_agent_context_override():
    """context parameter overrides state.context."""
    from __init__ import handle_run_agent
    state = {
        "request": "test",
        "category": "FEATURE",
        "pipeline": ["architect"],
        "current_idx": 0,
        "completed": [],
        "status": "running",
        "context": {"research": {"original": "from_state"}},
    }
    override = {"research": {"overridden": "yes"}, "planning": {}}
    result = json.loads(handle_run_agent({
        "state": state, "agent_id": "architect", "context": override
    }))
    assert result["agent_id"] == "architect"
    # prompt should contain overridden context
    assert "overridden" in result["prompt"]


def test_run_agent_path_traversal_guard():
    """Agent IDs with path traversal are sanitized."""
    from __init__ import handle_run_agent
    state = {"request": "x", "pipeline": ["finder"], "current_idx": 0, "status": "running"}
    result = json.loads(handle_run_agent({"state": state, "agent_id": "../finder"}))
    # Should resolve to "finder" after basename, not error
    assert "error" not in result
    assert result["agent_id"] == "finder"
```

---

## TASK-19: Верификация — прогнать проверки после всех правок

**Файлы:** все изменённые
**Тип:** CI/проверка (выполнить команды)
**Приоритет:** P1
**Зависит от:** TASK-01–18

После реализации ВСЕХ задач выполнить:

```bash
cd ~/git/hermes-pipeline-plugin

# 1. Линтер
ruff check __init__.py kanban.py

# 2. Синтаксис Python
python3 -c "import ast; ast.parse(open('__init__.py').read()); print('OK')"

# 3. YAML валидация
python3 -c "import yaml; yaml.safe_load(open('plugin.yaml')); print('OK')"

# 4. Проверить что provides_tools = 10
grep -c '\- ' plugin.yaml | head -1   # ожидается 10

# 5. Проверить что register_tool вызовов = 10
grep -c 'ctx.register_tool' __init__.py  # ожидается 10

# 6. Тесты
uv run pytest tests/test_init.py -v
```

---

## ⚠️ Pitfalls (обязательно прочитать перед началом)

1. **Stale code после правки.** Плагин грузится при старте сессии. После `patch` на `__init__.py` нужен рестарт Hermes-сессии (новый чат). `hermes plugins reload` не перезагружает Python-модули полностью.

2. **Экранирование `{}`.** `handle_run_agent` должен экранировать `request` и `category` перед `.format()`, так же как `handle_prompt`. Уже учтено в коде TASK-02.

3. **Path traversal guard.** `agent_id` передаётся как часть пути. Проверка `os.path.basename()` + `os.path.realpath()` как в `handle_prompt`. Уже учтено.

4. **call_args = null для direct.** Оркестратор не должен пытаться вызвать `delegate_task` если `call_args is None`. Скилл (TASK-14) проверяет `directive` перед вызовом.

5. **Скилл в двух местах.** Скилл лежит в репозитории (`skill/pipeline-orchestrator/SKILL.md`) и симлинком в `~/.hermes/skills/hermes/pipeline-orchestrator/SKILL.md`. Править нужно файл в репозитории (симлинк подхватит).

6. **ORDER MATTERS:** TASK-01–04 сначала, затем TASK-05, затем остальные. Иначе файлы будут неконсистентны.

---

## Резюме

| # | Файл | Что | Приоритет |
|---|------|-----|-----------|
| TASK-01 | `__init__.py` | RUN_AGENT_SCHEMA | P0 |
| TASK-02 | `__init__.py` | handle_run_agent handler | P0 |
| TASK-03 | `__init__.py` | register() +10th tool | P0 |
| TASK-04 | `__init__.py` | docstring v2.0→v2.1, 9→10 tools | P0 |
| TASK-05 | `plugin.yaml` | version 2.1.0 + pipeline_run_agent | P0 |
| TASK-06 | `AGENTS.md` | Tools(v2.0)→(v2.1), 9→10 | P1 |
| TASK-07 | `AGENTS.md` | +pipeline_run_agent в таблицу | P1 |
| TASK-08 | `AGENTS.md` | +Delegation Package секция | P1 |
| TASK-09 | `AGENTS.md` | Key Files + v2.0→v2.1 changes | P1 |
| TASK-10 | `ARCHITECTURE.md` | Заголовки + 9→10 | P1 |
| TASK-11 | `ARCHITECTURE.md` | Диаграмма + pipeline_run_agent | P1 |
| TASK-12 | `ARCHITECTURE.md` | Changelog строка v2.1.0 | P1 |
| TASK-13 | `SKILL.md` | Заголовок v2.0→v2.1, 9→10 | P1 |
| TASK-14 | `SKILL.md` | Delegation Rule секция | P1 |
| TASK-15 | `SKILL.md` | Tool #10 в Available Tools | P1 |
| TASK-16 | `SKILL.md` | Pipeline Flow обновление | P1 |
| TASK-17 | `kanban.py` | get_agent_context helper | P2 (опц.) |
| TASK-18 | `tests/test_init.py` | 8 тестов для run_agent | P1 |
| TASK-19 | Все | Верификация (ruff, pytest, grep) | P1 |
