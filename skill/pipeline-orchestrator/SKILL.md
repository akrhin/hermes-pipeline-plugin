---
name: pipeline-orchestrator
description: "Master orchestrator skill for Pipeline Plugin v3.3.3 — kanban.db SSOT, 16 agents, 8 categories, selective context, LLM Judge ensemble, deterministic convergence, hot-reload config."
author: Hermes Agent + Vladimir
category: hermes
tags: [pipeline, orchestrator, ensemble, convergence, kanban, retro, master]
---

# Pipeline Orchestrator v3.3.3 — Master Skill

**Единая точка входа для работы с pipeline plugin.** Загружай этот скилл ПЕРЕД каждым прогоном.

**Источник правды:** `~/git/hermes-pipeline-plugin` (репозиторий). Не используй память — здесь всё.

---

## 1. What This Is

Multi-agent пайплайн-оркестратор для Hermes Agent. 12 инструментов на SQLite.

**Variant C.** state.json удалён. kanban.db — единое состояние.

**Архитектура:**
```
User request → pipeline_classify → pipeline_save (создаёт дерево задач на kanban.db)
                     ↓
           ┌─ шагаю по таскам ──┐
           │  pipeline_resume()  │ (после рестарта)
           └──────────┬─────────┘
                      ↓
              pipeline_run_agent(state, agent_id) → delegation package
              pipeline_advance(state, agent) → promote next
                      ↓
              pipeline_convergence(state, findings) → decision
                      ↓
         converged? → pipeline_clear()
         continue?  → следующий раунд (coder single pass)
```

---

## 2. 16 Agents & 8 Categories

**Все 16 агентов. Не все запускаются в каждом прогоне.**

| Категория | Пайплайн | Всего |
|-----------|---------|-------|
| **SECURITY_RELATED** | finder → analyst → researcher → architect → planner → coder → reviewer → security → integration → tester → documenter | **11** |
| **BUG_UNKNOWN** | finder → debugger → fixer → reviewer → tester | **5** |
| **BUG_KNOWN** | finder → fixer → reviewer → tester | **4** |
| **REFACTORING** | finder → analyst → refactorer → reviewer → integration → tester | **6** |
| **PERFORMANCE** | finder → analyst → optimizer → reviewer → tester | **5** |
| **INFRASTRUCTURE** | finder → devops → reviewer → tester | **4** |
| **DOCUMENTATION** | finder → documenter | **2** |
| **FEATURE** | finder → analyst → architect → planner → coder → reviewer → integration → tester → documenter | **9** |

### Model Map

16 агентов, security — на Pro-делегации, остальные — Flash/direct.

| Агент | Тип | Модель | Контекст |
|-------|-----|--------|----------|
| @finder | direct | deepseek-v4-flash | research |
| @analyst | direct | deepseek-v4-flash | research |
| @researcher | direct | deepseek-v4-flash | research |
| @architect | direct | deepseek-v4-flash | research, planning |
| @planner | direct | deepseek-v4-flash | planning, infrastructure |
| @coder | direct | deepseek-v4-flash | implementation, planning |
| @fixer | direct | deepseek-v4-flash | implementation |
| @refactorer | direct | deepseek-v4-flash | implementation |
| @reviewer | direct | deepseek-v4-flash | implementation, research |
| @security | **delegate** | **deepseek-v4-pro** | implementation, research |
| @integration | direct | deepseek-v4-flash | implementation, documentation, infrastructure |
| @tester | direct | deepseek-v4-flash | implementation |
| @debugger | direct | deepseek-v4-flash | implementation |
| @documenter | direct | deepseek-v4-flash | implementation, documentation |
| @devops | direct | deepseek-v4-flash | infrastructure |
| @optimizer | direct | deepseek-v4-flash | implementation |

Конфиг: `~/.hermes/plugins/pipeline/config.yaml`. Hot-reload — перечитывается на каждый вызов. Приоритет: `agents.<agent_id> → defaults.<type> → BUILTIN_MODEL_MAP`.

---

## 3. Pipeline Loop (execution order)

```python
state = pipeline_resume() or pipeline_save({category, request, pipeline})

for idx, agent in enumerate(state["pipeline"]):
    if agent == "coder" and state["round"] <= 1 and ensemble_enabled:
        # === ENSEMBLE FLOW ===
        candidates = pipeline_ensemble_run(state, "coder", n=5)
        for c in candidates:
            result = delegate_task(goal=c["task"], context=c["context"])
            c["result"] = result
        
        judge_result = pipeline_ensemble_judge(request, candidates, judge_mode="llm")
        
        # ⚠️ CRITICAL: call delegate_task with judge_call_args
        llm_response = delegate_task(**judge_result["judge_call_args"])
        parsed = json.loads(llm_response)
        winner_id = parsed.get("winner_id", "candidate_3")
    else:
        # === SINGLE PASS ===
        pkg = pipeline_run_agent(state, agent)
        if pkg["directive"] == "delegate":
            result = delegate_task(**pkg["call_args"])
        else:  # direct
            result = <orchestrator executes prompt directly>
    
    state = pipeline_advance(state, agent)
```

---

## 4. LLM Judge Orchestration (CRITICAL — FROM THIS SKILL, NOT MEMORY)

**Баг #3 был в том, что оркестратор НЕ вызывал delegate_task с judge_call_args. Фикс ниже.**

### Шаги после pipeline_ensemble_judge:

```python
judge_result = json.loads(handle_ensemble_judge({
    "request": request,
    "candidates": candidates, 
    "judge_mode": "llm"
}))

if judge_result.get("judge_call_args"):
    llm_response = delegate_task(**judge_result["judge_call_args"])
    
    try:
        parsed = json.loads(llm_response)
        winner_id = parsed.get("winner_id", "candidate_3")
        rationale = parsed.get("rationale", "")
        scores = parsed.get("scores", [])
    except (json.JSONDecodeError, TypeError):
        winner_id = judge_result.get("winner_id", "candidate_3")
        rationale = "LLM Judge returned non-JSON — fallback"
        scores = []
else:
    winner_id = judge_result.get("winner_id", "candidate_3")

# winner → @reviewer
```

### Judge modes:

| Mode | Поведение |
|------|-----------|
| **deterministic** | Picks middle candidate (len//2). Returns `winner_id: candidate_3`. |
| **llm** | Returns `winner_id: null, judge_call_args: {...}`. Orchestrator MUST call `delegate_task`. |

### First real call (2026-07-20):
- winner: candidate_3 (T=0.7, Standard)
- Scores: candidate_1=22, candidate_2=30, candidate_3=**35**, candidate_4=31, candidate_5=29

---

## 5. Ensemble Variations

| ID | T | Strategy |
|----|---|----------|
| candidate_1 | 0.3 | Минимальные изменения |
| candidate_2 | 0.5 | Чистый код с type hints |
| candidate_3 | 0.7 | Standard production |
| candidate_4 | 0.9 | Полное решение с тестами |
| candidate_5 | 1.1 | Нестандартный подход |

---

## 6. Convergence Engine (deterministic)

```python
MAX_CONVERGENCE_ROUNDS = 3

# evaluate_convergence():
# 1. Фильтр: только findings со status != ("fixed", "accepted", "none")
# 2. P0/P1 → continue/maxed_out/stuck
# 3. Нет P0/P1 → converged
# 4. Fingerprint = hash(severity:file:category:description)
```

| Decision | Условие | Действие |
|----------|---------|----------|
| converged | Нет P0/P1 | pipeline_clear() |
| continue | Есть P0/P1, round < 3, fingerprint changed | Next round |
| maxed_out | round >= 3 | Hard stop, close children (bug #11) |
| stuck | fingerprint unchanged | Stop, require intervention |

---

## 7. Config (полный)

```yaml
pipeline:
  models:
    defaults:
      direct:
        model: deepseek-v4-flash
      delegate:
        provider: direct
        model: deepseek-v4-flash
    agents:
      security:
        provider: delegate
        model: deepseek-v4-pro

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

---

## 8. 12 Tools

| Tool | Output |
|------|--------|
| pipeline_classify(request) | {category, pipeline, matched_keywords} |
| pipeline_save(state) | {kanban_parent_id, kanban_task_ids} |
| pipeline_load() | state or None |
| pipeline_resume() | state or None |
| pipeline_advance(state, agent) | updated state |
| pipeline_clear() | close all tasks |
| agent_prompt(agent_id, context) | prompt string |
| agent_model(agent_id) | {provider, model} |
| pipeline_run_agent(state, agent) | {directive, prompt, call_args} |
| pipeline_ensemble_run(state, agent, n) | [candidates] |
| pipeline_ensemble_judge(request, candidates, mode) | {winner_id, rationale, judge_call_args} |
| pipeline_convergence(state, findings) | {decision, reason, p0_count, p1_count, p2_count} |

---

## 9. Bugfix History

| ID | Sev | File | Баг | Статус |
|----|-----|------|-----|--------|
| #1 | P1 | kanban.py | reopen() не существовал | ✅ |
| #3 | **P0** | ensemble.py | LLM Judge — заглушка (всегда candidate_3) | ✅ |
| #4 | **P0** | __init__.py | Flash-агенты с prompt:null | ✅ |
| #10 | P2 | integration.prompt | Мёртвый Full context | ✅ |
| #11 | P2 | kanban.py | maxed_out не закрывал детей | ✅ |
| #15 | P1 | kanban.py | stale cleanup пропускал 1-child | ✅ |
| #20 | P2 | kanban.py | scan_board без LIMIT 1 | ✅ |
| v3.3.2 | — | classify.py | RU keywords, word-boundary, priority | ✅ |
| **v3.3.3** | — | _orchestration_ | **LLM Judge: delegate_task с judge_call_args** | ✅ |

---

## 10. Pitfalls

1. **Состояние** — в kanban.db. После рестарта — `pipeline_resume()`.
2. **Ensemble только на round=0/1.** На round 2+ single pass.
3. **LLM Judge оркестрация** — загружать этот скилл перед каждым ensemble-прогоном. Не из памяти.
4. **judge.prompt удалён** — промпты генерируются программно.
5. **classify word-boundary** — `len(kw) < 5`, не `<= 5`. Иначе `crash` не матчит `crashes`.
