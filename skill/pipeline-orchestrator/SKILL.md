---
name: pipeline-orchestrator
description: Orchestration logic for Pipeline Plugin v2.0 (Kanban-native) — state in kanban.db, no state.json. Variant C: board is SSOT.
author: Hermes + Vladimir
category: hermes
tags: [pipeline, orchestration, multi-agent, quality-gates, kanban, variant-c]
---

# Pipeline Orchestrator v2.0 — Kanban-native (Variant C)

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

## Available Tools

Плагин регистрирует **9 инструментов** в toolset `pipeline`:

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

## Pipeline Flow (checkpoint-style)

```
1. classify(request)
   → {category, pipeline: [...]}

2. save({request, category, pipeline, status: "running"})
   → {kanban_parent_id, kanban_task_ids}

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
