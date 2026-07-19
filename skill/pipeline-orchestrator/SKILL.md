---
name: pipeline-orchestrator
description: Orchestration logic for Pipeline Plugin v2.1 (Kanban-native) — state in kanban.db, no state.json. Variant C: board is SSOT.
author: Hermes + Vladimir
category: hermes
tags: [pipeline, orchestration, multi-agent, quality-gates, kanban, variant-c]
---

# Pipeline Orchestrator v2.1 — Kanban-native (Variant C)

## Architecture

```
User request → pipeline_classify → pipeline_save (create task tree on board)
                    ↓
         ┌─ шагаю по таскам на доске ─┐
         │  pipeline_load() или        │
         │  pipeline_resume()          │
         │  → вижу какой @agent ready  │
         └──────────┬──────────────────┘
                    ↓
            выполняю агента
            pipeline_advance(state, agent)
            → promote следующего
                    ↓
         ┄ convergence round ┄
         pipeline_convergence(state, findings)
         → findings на доску, решение
                    ↓
         converged? → pipeline_clear()
         continue?  → следующий раунд
```

**Kлючевое отличие от v1.x:** нет `state.json`, нет `pstate.save()`/`load()`.  
Всё состояние — на доске `pipeline` в kanban.db.  
После рестарта: `pipeline_resume()` → сканирую доску → «ага, @coder done, @reviewer ready».

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

## Available Tools

Плагин регистрирует **10 инструментов** в toolset `pipeline`:

### 1. `pipeline_classify(request: str)`
Классифицирует запрос, возвращает `{category, pipeline, pipeline_type}`.
Вызывается **первым**.

### 2. `pipeline_save(state: dict)`
Создаёт дерево задач на доске pipeline:
- Parent: «🔷 Пайплайн: <request>»
- Children: по одному на каждого агента, с `--parent` линком
- Первый агент сразу в `ready`
- **Idempotent:** если parent уже существует (по idempotency-key), не дублирует

**Вызывается один раз** при старте пайплайна.

### 3. `pipeline_load()`
Сканирует доску pipeline, ищет активный (не done) parent.
Возвращает реконструированный state dict или **null**, если пайплайна нет.

### 4. `pipeline_resume()`
То же что `pipeline_load()`, но явный semantic:
- После `/resume` команды
- После рестарта сессии
- Когда хочешь проверить «а не висит ли что-то на доске?»

### 5. `pipeline_advance(state: dict, completed_agent: str)`
Отмечает агента как `done` и `promote` следующего в `ready`.
Возвращает обновлённый state с `current_idx` +1.

### 6. `pipeline_convergence(state: dict, findings?: list)`
Детерминированная конвергенция:
- Вычисляет fingerprint, сравнивает с предыдущим раундом
- Решает: `continue` / `converged` / `stuck` / `maxed_out`
- Пишет findings как comment на доску (через `kb.on_convergence`)
- На `continue`: разблокирует @coder для следующего раунда
- Состояние **не сохраняется на диск** — state в working memory агента

### 7. `pipeline_clear()`
Закрывает все задачи на доске (cancel/abort).
Комментирует «🧹 Пайплайн очищен».

### 8. `agent_prompt(agent_id, context, request?, category?)`
Читает `agents/<agent_id>.prompt`, подставляет контекст.
Возвращает `{prompt: "..."}`.

### 9. `agent_model(agent_id)`
Возвращает `{provider, model}` для агента.

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
- `"delegate_free"` → Free-tier (researcher). Аналогично delegate.
- `"direct"` → Flash-агенты. Оркестратор использует prompt напрямую в своём контексте.

## Pipeline Flow (checkpoint-style)

```
1. classify(request)
   → {category, pipeline: [...]}

2. save({request, category, pipeline, status: "running"})
   → {kanban_parent_id, kanban_task_ids}

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

## Checkpoints

Перед каждым ответственным этапом — спросить пользователя:
- После `@researcher` (перед архитектором): «Вот что нашёл, проектируем?»
- После `@planner` (перед кодером): «План устраивает?»
- После `@coder` (перед ревью): «Код готов, пускать ревьюера?»
- На каждой итерации конвергенции

Пользователь может сказать «да», «стоп», «продолжай без спроса».

## Resume After Restart

При старте новой сессии:

```
1. pipeline_resume()
2. Если вернул state:
   - Показать: «Есть незавершённый пайплайн: <request>, этап @<agent>, раунд N. Продолжаем?»
   - Если «да»: беру state, вызываю advance() для текущего ready-агента
   - Если «нет»: pipeline_clear()
3. Если null: работаем дальше, пайплайна нет
```

## Kanban Integration

Не вызывать `hermes kanban` напрямую. Всё через инструменты плагина:
- `pipeline_save` → создаёт дерево
- `pipeline_advance` → promote следующего
- `pipeline_convergence` → comment + complete/block/continue
- `pipeline_clear` → закрыть всё

На доске:
- Parent: статус `running` пока идёт, `done` когда converged/maxed_out, `blocked` если stuck
- Children: `todo` → `ready` → `running` → `done`

## Pitfalls

1. **Состояние в working memory.** После рестарта сессии state теряется — нужен `pipeline_resume()`.
2. **Idempotency ключи.** `pipeline_save` использует md5 от списка агентов. Если агенты совпадают — не дублирует. Если надо пересоздать — сначала `pipeline_clear()`.
3. **Kanban CLI формат.** `kanban.py` парсит `--json` вывод. Если Hermes изменит JSON-формат — `scan_board()` сломается.
4. **scan_board() ищет только доску pipeline.** Другие доски не трогает.
5. **state.json не существует.** Не пытайся читать `~/.hermes/plugins/pipeline/state.json` — его больше нет.
6. **Не сохраняй state вручную.** Всё состояние на доске. Кеш в рабочей памяти агента — временный.
7. **После рестарта Hermes** kanban.db жив. `pipeline_resume()` подхватит.
