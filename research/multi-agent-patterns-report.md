# Multi-Agent Orchestration Patterns — Research Report

**Date:** 2026-07-19  
**Context:** `pipeline_run_agent(state, agent_id)` — новый инструмент для pipeline plugin v2.0  
**Задача:** спроектировать автоматическое делегирование pipeline-агентов без ручного участия основного агента

---

## 1. Industry Landscape: Four Frameworks Compared

### 1.1 Anthropic — «Building Effective Agents» (Dec 2024)

**Ключевой принцип:** *«Success isn't about building the most sophisticated system. Start with simple prompts, add multi-step agentic systems only when simpler solutions fall short.»*

Пять канонических паттернов (workflows):

| Pattern | Описание | Когда применять |
|---------|----------|-----------------|
| **Prompt Chaining** | Последовательные LLM-вызовы: выход предыдущего → вход следующего | Задача легко разбивается на фиксированные подзадачи |
| **Routing** | Классификация входа → разный downstream по категории | Разные типы запросов требуют специализированной обработки |
| **Parallelization** | Sectioning (независимые подзадачи параллельно) или Voting (multiple perspectives) | Скорость или confidence через множественные проходы |
| **Orchestrator-Workers** ⭐ | Центральный LLM динамически делит задачу, делегирует worker'ам, синтезирует результат | Сложные задачи, где подзадачи НЕ известны заранее |
| **Evaluator-Optimizer** | Generator → Evaluator (feedback) → loop | Чёткие критерии оценки + итеративное улучшение |

**Autonomous Agents:** LLM в цикле с tools, сам решает что делать, может работать много шагов. Требует доверия и guardrails.

**Claude Code sub-agents:** «Spawn multiple Claude Code agents that work on different parts simultaneously. A lead agent coordinates, assigns subtasks, and merges results.» — **Это ближайший аналог нашего пайплайна.**

**Релевантность для Hermes:**
- **Orchestrator-Workers** — идеальное совпадение: главный Hermes-агент = orchestrator, pipeline agents = workers
- **Evaluator-Optimizer** — соответствует convergence loop: coder → reviewer → security → tester → documenter → convergence evaluation → repeat
- **Prompt Chaining** — соответствует последовательности агентов в пайплайне: finder → analyst → ... → documenter

---

### 1.2 AutoGen (Microsoft) — Core API Design Patterns

Два документированных паттерна:

**Group Chat:**
- Все агенты делят общий топик сообщений
- `GroupChatManager` выбирает следующего спикера (LLM-based selector или round-robin)
- Строго последовательно: один агент работает в каждый момент
- Агенты — специализированные `RoutedAgent` с разными system messages
- Pub/sub через `TopicId`: агент публикует в общий топик, менеджер выбирает следующего

**Reflection:**
- Пара агентов: Coder → Reviewer (обратная связь) → цикл до approval
- Явный message protocol: `CodeWritingTask` → `CodeReviewTask` → `CodeReviewResult` (approved? → done : loop)
- Coder хранит session memory по task_id

**Ключевое отличие от Hermes:** AutoGen использует `SingleThreadedAgentRuntime` — центральный event loop, который роутит сообщения между агентами по топикам. Все агенты живут в одном рантайме.

**Релевантность для Hermes:**
- **Group Chat Manager** = аналог «супервизора», который решает кто следующий. Но у нас последовательность фиксирована (pipeline agents list), поэтому LLM-based selector избыточен.
- **Reflection** = точный аналог нашего convergence loop (coder ↔ reviewer/security/tester), но в AutoGen это peer-to-peer сообщения, а у нас — через основной агент.
- Message protocol AutoGen'а жёстко типизирован (dataclasses), у нас — ad-hoc dict через kanban.

---

### 1.3 LangGraph (LangChain)

**Архитектура:** StateGraph = State + Nodes + Edges
- **State:** shared schema (TypedDict/Pydantic), reducer functions для merge-логики
- **Nodes:** функции (могут содержать LLM или просто код), читают state → возвращают обновление
- **Edges:** фиксированные или conditional (routing на основе state)
- **Pregel-inspired:** «super-steps» — параллельные ноды в одном шаге, последовательные в разных

**Multi-agent:** каждый агент — отдельный subgraph или node. Routing между агентами через conditional edges.

**Ключевые фичи:**
- **Persistence (checkpoints):** состояние сохраняется после каждого super-step, можно возобновить
- **Human-in-the-loop (interrupts):** пауза для human approval на любом шаге
- **Streaming:** real-time видимость выполнения
- **Multiple schemas:** private state channels между нодами (не exposed в input/output)

**Релевантность для Hermes:**
- **StateGraph** — очень близко к нашей архитектуре: kanban = persistence layer, state dict = working memory
- **Conditional edges** — аналог convergence evaluation: `continue? → coder : converged? → done : stuck? → human`
- **Checkpoints** — у нас `pipeline_resume()` после рестарта сессии
- **Избыточно:** LangGraph — это framework, требующий деплоя. Нам не нужен Pregel runtime — у нас всё состояние на доске, а «рантайм» — это основной Hermes agent.
- **НО:** идея private state channels может быть полезна — часть состояния передавать между шагами пайплайна, не загрязняя контекст основного агента.

---

### 1.4 CrewAI Flows

**Архитектура:** Event-driven flow через декораторы
- `@start()` — entry points (может быть несколько, выполняются параллельно)
- `@listen(method)` — triggered когда указанный метод завершился
- State management: unstructured (dict) или Pydantic BaseModel
- Memory built-in: `self.remember()`, `self.recall()`, `self.extract_memories()`
- Flows могут запускать Crews как шаги

**Пример паттерна:**
```python
class ExampleFlow(Flow):
    @start()
    def generate_city(self): ...

    @listen(generate_city)
    def generate_fun_fact(self, random_city): ...  # auto-receives output
```

**Релевантность для Hermes:**
- **@listen декоратор** — элегантный способ связать шаги. Но у нас последовательность жёсткая и известна заранее (pipeline agents list), а CrewAI Flow хорош для ad-hoc цепочек.
- **State management** — Pydantic модель для pipeline state могла бы заменить ad-hoc dict. Но у нас состояние на доске, а не в памяти.
- **Memory across runs** — у CrewAI есть persistent memory (LanceDB), у нас — kanban + session DB.
- **Flow plotting** — визуализация pipeline была бы полезна для отладки (HTML граф).

---

## 2. Hermes Agent Internals: delegate_task Mechanics

### 2.1 Agent-Level Tool Interception

**Критическое открытие:** `delegate_task` — это **agent-level tool**. Он перехватывается в `run_agent.py` ДО того, как вызов дойдёт до `handle_function_call()` / registry.

Из документации:
```
Agent-Level Tools (intercepted by run_agent.py BEFORE reaching handle_function_call):
| Tool            | Why intercepted                                    |
|-----------------|----------------------------------------------------|
| todo            | Reads/writes agent-local task state                |
| memory          | Writes to persistent memory files                  |
| session_search  | Queries session history via agent's session DB     |
| delegate_task   | Spawns subagent(s) with isolated context           |
```

**Что это значит для плагина:**
- Когда модель вызывает `delegate_task`, AIAgent сам его обрабатывает — создаёт под-агента, запускает сессию
- Результат возвращается как synthetic tool result в conversation history основного агента
- Плагин **НЕ МОЖЕТ** вызвать delegate_task из своего handler'а — handler это обычная Python-функция, у него нет доступа к AIAgent instance

### 2.2 Plugin Tool Execution Flow

```
Model response with tool_call
  → run_agent.py agent loop
    → model_tools.handle_function_call(name, args, task_id)
      → [Agent-loop tools?] delegate_task/todo/memory/session_search → handled by agent loop
      → [Plugin pre-hook]
      → registry.dispatch(name, args) → Plugin handler function
      → [Plugin post-hook]
```

Плагин получает `args` (то что модель передала в tool call) и `**kwargs` (контекст). **Нет доступа к AIAgent, нет возможности spawn subagent.**

### 2.3 Subagent Lifecycle

1. Main agent tool_call: `delegate_task(prompt="...", model="deepseek-v4-flash")`
2. AIAgent создаёт subagent с изолированным контекстом (свой iteration budget ≤ delegation.max_iterations)
3. Subagent работает (tool calls, API calls) до completion
4. Результат (текст) вставляется в conversation history основного агента как tool result
5. Основной агент продолжает loop, видит результат, решает что делать дальше

### 2.4 Callback Surfaces

Доступные callbacks (из agent loop):
- `tool_progress_callback` — до/после каждого tool execution
- `step_callback` — после каждого полного turn'а агента
- Нет callback'а «subagent completed» для плагинов

---

## 3. Текущий Pipeline Plugin: Как работает делегирование сейчас

### 3.1 Текущий поток (полу-ручной)

```
Основной агент (я):
  1. pipeline_load() / pipeline_resume()
  2. Вижу: @coder ready
  3. agent_prompt("coder", context) → получаю промпт
  4. agent_model("coder") → получаю {provider, model}
  5. Сам вызываю delegate_task(prompt, model=...)
  6. delegate_task завершён → результат в контексте
  7. pipeline_advance(state, "coder") → promote @reviewer
  8. Повторяю для следующего агента
```

**Проблема:** шаги 3-7 — человек (основной агент) должен помнить последовательность. Можно забыть, перепутать модель, не вызвать advance.

### 3.2 MODEL_MAP в plugin

```python
MODEL_MAP = {
    "coder":   {"provider": "direct", "model": "deepseek-v4-flash"},
    "architect": {"provider": "delegate", "model": "deepseek-v4-pro"},
    "researcher": {"provider": "delegate_free", "model": "openrouter/free"},
    ...
}
```

`"direct"` означает «основной агент делает сам, без delegate_task». `"delegate"` — через delegate_task. `"delegate_free"` — через delegate_task с бесплатной моделью.

### 3.3 Оркестратор (skill)

Скилл `pipeline-orchestrator` содержит логику цикла:
```
for each agent in pipeline:
    prompt = agent_prompt(agent, context)
    run_agent(agent, prompt)  ← delegate_task или прямо
    advance(state, agent)
```

Но execute этого цикла — на основном агенте. Скилл — это prompt, не код.

---

## 4. Сравнительный Анализ Паттернов

| Паттерн | Anthropic | AutoGen | LangGraph | CrewAI | **Hermes Pipeline v2.0** |
|---------|-----------|---------|-----------|--------|---------------------------|
| **Supervisor/Orchestrator** | ✅ Orchestrator-Workers | ✅ GroupChatManager | ✅ Supervisor agent + subgraphs | ✅ Flow orchestrating Crews | ✅ Основной агент оркестрирует pipeline |
| **Chain/Sequence** | ✅ Prompt Chaining | ⚠️ Implicit via topics | ✅ Fixed edges | ✅ @listen chaining | ✅ pipeline agent list (фиксированная последовательность) |
| **Routing** | ✅ Routing workflow | ✅ LLM-based speaker selection | ✅ Conditional edges | ✅ Router steps | ⚠️ MODEL_MAP определяет direct vs delegate |
| **Parallelization** | ✅ Sectioning + Voting | ⚠️ Through topics | ✅ Parallel nodes (same super-step) | ✅ Multiple @start() | ❌ Нет — строго последовательно |
| **Reflection/Convergence** | ✅ Evaluator-Optimizer | ✅ Reflection pattern | ✅ Cyclic graphs | ⚠️ Implicit via Crew tasks | ✅ convergence loop (coder→reviewer→security→tester→evaluate) |
| **State Management** | Application-level | Message-based (per session) | StateGraph with reducers | Pydantic/dict in Flow | kanban.db task tree + state dict |
| **Human-in-the-loop** | Checkpoints | UserAgent in group chat | Interrupts | Guardrails + callbacks | Checkpoints в скилле (спросить пользователя) |
| **Persistence** | Application-level | In-memory (runtime) | SQLite checkpointer | LanceDB | kanban.db (persistent after restart) |
| **Delegation Mechanism** | Claude Code sub-agents | Pub/sub topics | Subgraph invocation | Crew inside Flow | `delegate_task` (agent-level tool) |

### Вывод по сравнению:

1. **Ближайший аналог нашего пайплайна — Anthropic Orchestrator-Workers + Evaluator-Optimizer.** Фиксированная последовательность агентов = Prompt Chaining, convergence loop = Evaluator-Optimizer.

2. **LangGraph StateGraph** — архитектурно ближе всего (state → nodes → edges → persistence), но это framework, а нам нужен встроенный в Hermes инструмент.

3. **AutoGen Group Chat** — избыточен. LLM-based speaker selection не нужен, когда последовательность фиксирована.

4. **CrewAI Flows** — хорош для ad-hoc композиции, но у нас pipeline предопределён.

---

## 5. Рекомендации для `pipeline_run_agent`

### 5.1 Архитектурное ограничение

**Плагин НЕ может вызвать `delegate_task` напрямую.** `delegate_task` — agent-level tool, перехватывается AIAgent'ом до registry dispatch. Handler плагина не имеет доступа к AIAgent instance.

Есть два пути:
- **Путь A:** Модифицировать ядро Hermes для поддержки программируемого делегирования из плагинов
- **Путь B:** Работать в рамках текущей архитектуры — плагин подготавливает делегирование, основной агент исполняет

### 5.2 Рекомендованный дизайн: Путь B (без изменений ядра)

**Паттерн: Supervisor-Orchestrator с автоматической подготовкой**

`pipeline_run_agent(state, agent_id)` — новый инструмент:

```
Handler (в плагине):
  1. Вызывает agent_prompt(agent_id, context) — чтение .prompt файла
  2. Вызывает agent_model(agent_id) — поиск provider/model в MODEL_MAP
  3. Возвращает structured delegation package
```

**Формат возврата:**
```json
{
  "status": "ready",
  "agent": "coder",
  "prompt": "You are a coder. Fix the bug...",
  "provider": "polza",
  "model": "deepseek-v4-flash",
  "mode": "delegate",
  "kanban_task_id": "abc123",
  "next": {
    "action": "delegate_task",
    "args": {
      "prompt": "<prompt from above>",
      "model": "deepseek-v4-flash"
    },
    "after": "pipeline_advance(state, 'coder')"
  }
}
```

**Поток выполнения (основной агент):**
```
1. pipeline_resume() → state
2. pipeline_run_agent(state, "coder")
   → возвращает delegation package
3. delegate_task(prompt="...", model="deepseek-v4-flash")
   → spawn subagent, получить результат
4. pipeline_advance(state, "coder")
   → mark done, promote @reviewer
5. [повторить для следующего агента]
```

**Ключевое отличие от текущего:** основной агент не должен САМ вычислять prompt и model — `pipeline_run_agent` делает это за него и выдаёт готовую инструкцию.

### 5.3 Усиление оркестратора

**Скилл `pipeline-orchestrator` должен быть расширен правилом:**

```
## Delegation Rule (CRITICAL)

When you receive a pipeline_run_agent result with status "ready":
  1. IMMEDIATELY call delegate_task with the exact prompt, provider, and model from the result
  2. Do NOT modify the prompt. Do NOT add your own instructions.
  3. Do NOT do anything else before calling delegate_task.
  4. When delegate_task returns, IMMEDIATELY call pipeline_advance with
     the same state and agent from the pipeline_run_agent result.
  5. Do NOT interpret or summarize the delegate's output before calling pipeline_advance.
     Call advance FIRST, then you can report results.
  6. Then proceed to the next agent: call pipeline_run_agent again.
```

Это делает оркестратор **детерминированным на уровне промпта** — навык жёстко предписывает последовательность действий, снижая риск ошибки.

### 5.4 Продвинутый вариант: Путь A (изменение ядра Hermes)

Если допустимо изменить ядро, можно добавить hook для плагинов:

```python
# В run_agent.py: после handle_function_call()
if tool_name == "pipeline_run_agent":
    result = registry.dispatch("pipeline_run_agent", args)
    if result.get("mode") == "delegate":
        # Автоматически spawn delegate_task
        delegate_result = self._handle_delegate_task(
            prompt=result["prompt"],
            model=result["model"]
        )
        # Автоматически вызвать pipeline_advance через ещё один tool call
        ...
```

**НО:** это требует доступа к исходному коду Hermes Agent (закрытый) и создаёт tight coupling между плагином и ядром.

### 5.5 Рекомендация: Route-aware pipeline_run_agent

MODEL_MAP уже различает три режима:
- `direct` → основной агент выполняет сам (не нужно delegate_task)
- `delegate` → delegate_task с pro-моделью
- `delegate_free` → delegate_task с бесплатной моделью

`pipeline_run_agent` должен возвращать **разные `next.action` в зависимости от mode**:

| agent | mode | next.action |
|-------|------|-------------|
| coder | direct | `null` (основной агент делает сам) |
| architect | delegate | `delegate_task` |
| researcher | delegate_free | `delegate_task` |

---

## 6. Callback Problem: Как pipeline_advance узнаёт о завершении?

### Текущая проблема

После `delegate_task` основной агент получает результат и ДОЛЖЕН вызвать `pipeline_advance`. Если он забудет — пайплайн зависнет.

### Решения (в порядке предпочтения):

1. **Prompt enforcement (рекомендовано):**
   - Оркестратор-скилл содержит жёсткое правило: «после delegate_task ВСЕГДА вызывай pipeline_advance»
   - `pipeline_run_agent` возвращает `next.after` с точной инструкцией
   - При следующем `pipeline_resume()` (после рестарта) — детектится расхождение и чинится

2. **Post-tool hook:**
   - Плагин регистрирует `post_tool_call` hook
   - После ЛЮБОГО delegate_task (не только pipeline) проверяет kanban — висит ли ready-агент без advance?
   - НО: hook получает результат инструмента, но не знает контекст пайплайна

3. **Pipeline health check (периодический):**
   - `pipeline_resume()` проверяет: если агент в `running`, но его нет среди активных делегатов → broken, auto-heal
   - Это уже частично реализовано в `scan_board()`

4. **Idempotent advance:**
   - `pipeline_advance` можно вызывать несколько раз для одного агента — он проверяет completed и не дублирует
   - Это даёт защиту от double-advance при retry

---

## 7. Итоговые Рекомендации

### Архитектурный паттерн для pipeline_run_agent

**«Prepared Orchestrator-Workers»** — гибрид трёх подходов:

| Источник | Что берём |
|----------|-----------|
| **Anthropic** | Orchestrator-Workers: центральный агент делегирует worker'ам. Evaluator-Optimizer: convergence loop |
| **LangGraph** | Persistence (checkpoints = kanban). State transitions через conditional evaluation |
| **CrewAI** | Structured delegation package (prompt + model + next actions) |

### Конкретный план реализации

**Новый инструмент: `pipeline_run_agent(state, agent_id)`**

```python
# В __init__.py плагина
RUN_AGENT_SCHEMA = {
    "name": "pipeline_run_agent",
    "description": "Prepare an agent for execution. Returns delegation instructions. For 'direct' mode agents, returns the prompt for inline execution. For 'delegate' agents, returns delegate_task parameters. ALWAYS follow the returned next.action exactly.",
    "parameters": {
        "type": "object",
        "properties": {
            "state": {"type": "object", "description": "Current pipeline state"},
            "agent_id": {"type": "string", "description": "Agent identifier (coder, reviewer, ...)"},
        },
        "required": ["state", "agent_id"],
    },
}

def handle_run_agent(args, **kwargs):
    state = args["state"]
    agent_id = args["agent_id"]
    
    # 1. Get agent prompt
    prompt_result = handle_prompt({"agent_id": agent_id, "context": state.get("context", {}), ...})
    prompt_data = json.loads(prompt_result)
    
    # 2. Get agent model
    model_result = handle_model({"agent_id": agent_id})
    model_data = json.loads(model_result)
    
    provider = model_data.get("provider", "direct")
    model = model_data.get("model", "")
    prompt = prompt_data.get("prompt", "")
    
    # 3. Determine mode
    mode = "inline" if provider == "direct" else "delegate"
    if provider == "delegate_free":
        mode = "delegate"
    
    # 4. Build delegation package
    result = {
        "status": "ready",
        "agent": agent_id,
        "mode": mode,
        "prompt": prompt,
        "model": model,
        "provider": provider,
    }
    
    if mode == "delegate":
        result["next"] = {
            "action": "delegate_task",
            "args": {"prompt": prompt, "model": model},
            "after": f"pipeline_advance(state, '{agent_id}')",
            "instruction": "IMMEDIATELY call delegate_task with the exact args above. Then IMMEDIATELY call pipeline_advance."
        }
    
    return json.dumps(result, ensure_ascii=False)
```

### Что нужно сделать:

1. **В плагин (`__init__.py`):**
   - Добавить `RUN_AGENT_SCHEMA` и `handle_run_agent`
   - Зарегистрировать как 10-й инструмент в `register(ctx)`

2. **В скилл (`pipeline-orchestrator/SKILL.md`):**
   - Добавить Delegation Rule (см. раздел 5.3)
   - Обновить Pipeline Flow: вместо `agent_prompt → delegate_task → advance` → просто `pipeline_run_agent → delegate_task → advance`

3. **В AGENTS.md плагина:**
   - Обновить таблицу инструментов (10 вместо 9)

4. **Опционально:**
   - Добавить `pipeline_health_check()` — проверяет расхождение kanban и реального состояния
   - Добавить idempotent guard в `pipeline_advance`

### Риски и mitigation:

| Риск | Mitigation |
|------|------------|
| Основной агент игнорирует `next.action` | Prompt enforcement в скилле. Если агент отклонился — `pipeline_resume` детектит и предлагает продолжить |
| Модель меняет prompt перед delegate_task | `next.instruction` говорит «Do NOT modify the prompt» |
| Double-advance | `pipeline_advance` проверяет completed и не дублирует |
| Изменение формата delegate_task в Hermes | Следить за changelog Hermes, тестировать на новых версиях |

---

## Приложение: Comparative Summary Table

| Framework | Pattern | Delegation Mechanism | State | Strengths | Weaknesses |
|-----------|---------|---------------------|-------|-----------|------------|
| **Anthropic** | Orchestrator-Workers | Sub-agents (Claude Code) | Application-managed | Simple, no framework overhead | Manual orchestration |
| **AutoGen** | Group Chat / Reflection | Pub/sub topics | In-memory per session | Strong typing, message protocols | Requires runtime, overengineered for fixed pipelines |
| **LangGraph** | StateGraph (Pregel) | Subgraph nodes | Checkpointed StateGraph | Persistence, streaming, conditional routing | Heavy framework, deployment complexity |
| **CrewAI** | Flows (@start/@listen) | Crew inside Flow | Pydantic/dict | Event-driven, simple API | Implicit coupling, less control |
| **Hermes Pipeline v2.0** | **Prepared Orchestrator-Workers** | `delegate_task` (agent-level tool) | kanban.db | No new runtime, kanban = persistence, deterministic convergence | Plugin can't directly call delegate_task |
