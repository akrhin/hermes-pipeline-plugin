---
name: pipeline-orchestrator
description: Orchestration logic for Pipeline Plugin v3.1 (Kanban-native + Ensemble) — kanban.db SSOT, selective context, Best-of-N ensemble.
author: Hermes + Vladimir
category: hermes
tags: [pipeline, orchestration, multi-agent, quality-gates, kanban, ensemble, variant-c]
---

# Pipeline Orchestrator v3.1 — Kanban-native + Ensemble

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
            выполняю агента с selective context
            pipeline_advance(state, agent)
            → promote следующего
                    ↓
         ┄ convergence round ┄
         pipeline_convergence(state, findings)
         → findings на доску, решение
                    ↓
         converged? → pipeline_clear()
         continue?  → @coder single pass (ensemble OFF)
```

## 🚨 Delegation Rule (CRITICAL)

Используй `pipeline_run_agent(state, agent_id)` для всех агентов:

1. Вызови `pipeline_run_agent(state, agent_id)` → получи delegation package
2. Для Pro (architect, reviewer, security, integration):
   - Прочитай `call_args` → `delegate_task(**call_args)`
3. Для Flash (finder, analyst, coder, tester и др.):
   - Используй prompt напрямую (directive: "direct")
4. Вызови `pipeline_advance(state, agent_id)` → promote следующего
5. **Никогда не вызывай delegate_task напрямую — всегда через pipeline_run_agent**

## Ensemble Flow (NEW v3.0+)

Для @coder на первом convergence round (round=0):

```
if agent == 'coder' and state.round <= 1 and ensemble enabled (config.yaml):

  1. pipeline_ensemble_run(state, 'coder', n=5)
     → generate_candidates(): 5 вариаций T=0.3..1.1
     → create_ensemble_subtasks(): N подтасков на доске

  2. delegate_task × 5 (параллельно)
     → каждый candidate: {prompt, model: deepseek-v4-flash, temperature}

  3. pipeline_ensemble_judge(request, results, judge_mode='llm')
     → mode='deterministic': выбирает среднего (быстро, MVP)
     → mode='llm': build_judge_prompt() → делегация в LLM Judge
     → возвращает {winner_id, rationale, scores}

  4. Результат (выбранный код) → @reviewer как обычно

else:
  → обычный single pass @coder
  → на convergence rounds (2+) ensemble auto-off (экономия)
```

## Available Tools

Плагин регистрирует **12 инструментов** в toolset `pipeline`:

### 1. `pipeline_classify(request: str)`
Классифицирует запрос, возвращает `{category, pipeline, pipeline_type}`.

### 2. `pipeline_save(state: dict)`
Создаёт дерево задач на доске pipeline. Idempotent.

### 3. `pipeline_load()` / `pipeline_resume()`
Сканирование доски, возврат state. После рестарта — `pipeline_resume()`.

### 4. `pipeline_advance(state: dict, completed_agent: str)`
Mark done + promote next.

### 5. `pipeline_convergence(state: dict, findings?: list)`
Детерминированная конвергенция (fingerprint, severity, max_rounds).

### 6. `pipeline_clear()`
Close all tasks.

### 7. `agent_prompt(agent_id, context, request?, category?)`
Читает шаблон `agents/<agent_id>.prompt`, подставляет ТОЛЬКО нужные секции контекста (AGENT_CONTEXT_FIELDS). Больше НЕ передаёт full_context.

### 8./9. `agent_model(agent_id)` / `pipeline_run_agent(state, agent_id, context?)`
Model routing + delegation package.

### 10./11. `pipeline_ensemble_run(state, agent_id, n?)` / `pipeline_ensemble_judge(request, candidates, judge_mode?)`
Best-of-N ensemble: генерация N вариаций + выбор лучшей.

## Selective Context (v2.3+)

Раньше каждый агент получал `full_context = json.dumps(весь контекст)`. Теперь:

| Агент | Получает | НЕ получает |
|-------|----------|-------------|
| @coder | implementation + planning | research, quality, docs, infra |
| @reviewer | implementation + research | planning, quality, docs, infra |
| @security | implementation + research | planning, quality, docs |
| @integration | implementation + documentation + infra | research, quality |
| @tester | implementation | всё остальное |
| @documenter | implementation + documentation | research, planning, quality |

Full_context доступен только для fallback (неизвестные агенты, backward compat).

## Config

```yaml
pipeline:
  models:
    # model per agent
  ensemble:
    enabled: true
    default_n: 5
    max_n: 10
    agents:
      coder:
        enabled: true
        n: 5
        judge_mode: llm
    judge:
      model: deepseek-v4-flash
      provider: polza
    cost_optimization:
      disable_on_round_gt: 1
```

## Pipeline Flow

```
1. classify(request) → {category, pipeline}

2. save({request, category, pipeline, status: "running"})
   → {kanban_parent_id, kanban_task_ids}

3. Цикл по агентам с selective context:
   for each agent in pipeline[current_idx:]:
     pkg = pipeline_run_agent(state, agent)
     if pkg.directive in ("delegate", "delegate_free"):
       result = delegate_task(**pkg.call_args)
     elif pkg.directive == "direct":
       # выполняю prompt напрямую
       result = <мой вывод>
     
     # Если @coder и round=0 и ensemble enabled:
     #   pipeline_ensemble_run → 5 candidates
     #   delegate_task × 5
     #   pipeline_ensemble_judge → winner
     
     state = pipeline_advance(pkg.state, agent)

4. Конвергенция:
   findings = собрать из результатов
   decision = pipeline_convergence(state, findings)
   continue? → раунд 2:
     1. pipeline_run_agent(state, "coder") → single pass (ensemble OFF)
     2. delegate_task / direct (результаты)
     3. Затем reviewer → security → ... → documenter
   converged? → готово, pipeline_clear()
   stuck? → показать findings, ждать пользователя

5. checkpoint? — спросить пользователя на ключевых этапах
```

## Pitfalls

1. **Состояние в working memory.** После рестарта — `pipeline_resume()`.
2. **Idempotency.** `pipeline_save` использует md5. Для пересоздания — `pipeline_clear()`.
3. **Kanban CLI формат.** `_kanban()` парсит JSON. Если Hermes изменит формат — сломается.
4. **Ensemble только на round=0.** На round 1+ single pass (экономия).
5. **AGENT_CONTEXT_FIELDS** — если добавил нового агента, пропиши ему секции контекста. Unknown fallback передаёт всё (backward compat).
6. **state.json не существует.** Не пытайся читать — его нет.
