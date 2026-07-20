---
name: pipeline-orchestrator
description: "Главный оркестратор-скилл for Pipeline Plugin v3.3.4 — kanban.db SSOT, 16 agents, 8 categories, selective context, LLM Judge ensemble, deterministic convergence, hot-reload config, toolsets override docs."
author: Hermes Agent + Vladimir
category: hermes
tags: [pipeline, orchestrator, ensemble, convergence, kanban, retro, master]
---

# Pipeline Orchestrator v3.3.4 — Главный оркестратор-скилл

## ⚠️ ПРАВИЛА РАБОТЫ С ПРОЕКТОМ (читать ПЕРЕД КАЖДЫМ ПРОГОНОМ)

**Этот раздел — закон. Не пропускай ни один пункт, не говори «потом», не оставляй todo в ответах.**

### Фаза 1: Получение задачи → Декомпозиция
1. Прочитай README.md, AGENTS.md, ARCHITECTURE.md, CHANGELOG.md, plugin.yaml
2. Узнай текущую версию, что уже сделано, кто авторы
3. Разбей задачу на шаги. Запиши в todo. Не начинай исполнение без плана.

### Фаза 2: Исполнение
4. Работай через pipeline: classify → save → load/resume → advance
5. Не bypass kanban — ни одного прямого delegate_task вне пайплайна
6. Каждые 5-7 вызовов инструментов — промежуточный вердикт: что сделано, что дальше

### Фаза 3: Документация (В КОНЦЕ ПРОГОНА, ПЕРЕД ПУШЕМ)
**Обновить ВСЕ эти файлы, если задача их затрагивает:**
- [ ] **plugin.yaml** — версия, описание
- [ ] **CHANGELOG.md** — новая запись с датой, список изменений (что, почему, кем)
- [ ] **AGENTS.md** — агенты, промпты, таблица категорий
- [ ] **ARCHITECTURE.md** — миграция v?.?.? в таблице истории
- [ ] **ARCHITECTURE-FIXES.md** — если фиксил баги
- [ ] **CONTRIBUTORS.md** — если работал с чужим PR
- [ ] **README.md** — если изменился quick start, установка, требования

### Фаза 4: Скиллы и инструменты (В КОНЦЕ ПРОГОНА)
- [ ] **skill/pipeline-orchestrator/SKILL.md** — если изменилась оркестрация, агенты, конфиг, баги
- [ ] **skill/pipeline-ensemble/SKILL.md** — если ensemble изменился
- [ ] **skill/pipeline-audit-checklist/SKILL.md** — если добавились баги или проверки
- [ ] Синхронизировать symlinks: `~/.hermes/skills/` → `~/git/hermes-pipeline-plugin/skill/`

### Фаза 5: Пуш
- [ ] `git add -A && git commit -m "v?.?.?:"` — осмысленное сообщение
- [ ] `git push origin main`
- [ ] Верификация: `pytest tests/ -q` (79/79), `ruff check .` (0 errors)

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

## 10. ⚠️ CRITICAL: Kanban Bypass Rule

**Когда pipeline task существует на доске — НИКОГДА не запускай агентов вручную.**
Не делай `delegate_task` напрямую. Оркестратор:

```
pipeline_classify → pipeline_save → pipeline_load/pipeline_resume → pipeline_advance(state, agent)
```

Последствия ручного запуска:
- Агент не в пайплайне — теряется sequencing
- Состояние расходится: kanban.db говорит `ready`, а агент уже отработал
- Convergence не видит результаты — бесконечный цикл или ложный `converged`
- Retro-логи не пишутся

## 11. Python Plugin Gotchas (удалён pipeline-testing-gotchas)

### Ruff I001 на try/except
Не используй многострочные `from .x import (...)` внутри try/except:
```python
# ❌ Ломает ruff I001
try:
    from .ensemble import (generate_candidates, judge_candidates)
except ImportError:
    from ensemble import (generate_candidates, judge_candidates)

# ✅ Одна строка на импорт
try:
    from .ensemble import generate_candidates, judge_candidates
except ImportError:
    from ensemble import generate_candidates, judge_candidates
```

### scan_board picks wrong parent
Если несколько pipeline parent-ов (мусор от старых прогонов):
```python
# Всегда: фильтр child_task_ids + sort by created_at DESC
rows = cursor.execute("SELECT * FROM tasks WHERE status IN ('ready','todo','running') ORDER BY created_at DESC LIMIT 5").fetchall()
```

### P1 findings — self-resolve
Если нашёл и исправил P1 в том же раунде — **помечай как P2**, а не P1. Иначе:
- severity=P1 → convergence видит «1 P1 остался» → continue
- severity=P2 → convergence видит 0 P0/P1 → converged

### Context-mode для анализа больших кодбаз
Не тащи 10+ файлов `read_file` + reasoning в контекст. Используй `execute_code()`:
```python
from hermes_tools import terminal, read_file, search_files
r = terminal("cd ~/project && grep -rn 'TODO' --include='*.py' . | head -20")
# Анализ в sandbox, не в контексте агента
```

## 12. Retro Log Analysis (удалён Pipeline Self-Analysis & Retro)

Ретро-логи: `~/.hermes/plugins/pipeline/retro/pipe_*.jsonl`

```bash
# Сводка convergence по всем прогонам
cat ~/.hermes/plugins/pipeline/retro/pipe_*.jsonl | python3 -c "
import sys,json
for line in sys.stdin:
    e = json.loads(line)
    if e.get('event') == 'convergence':
        print(e.get('run','')[:20], e['decision'], e.get('p0',0), e.get('p1',0))
"

# Дельта-анализ: сравнить findings между двумя прогонами
python3 -c "
import json, glob
def load(run_prefix):
    evts = []
    for f in glob.glob('$HOME/.hermes/plugins/pipeline/retro/*.jsonl'):
        for line in open(f):
            e = json.loads(line)
            if e.get('run','').startswith(run_prefix):
                evts.append(e)
    return evts
v1 = load('pipe:f3c9')
v2 = load('pipe:af9d')
for v in [v1,v2]:
    conv = [e for e in v if e['event']=='convergence']
    if conv: print(conv[-1]['run'][:20], conv[-1]['decision'])
"

# Fingerprint analysis
python3 -c "
import hashlib
def fp(findings):
    items = sorted(f\"{f.get('severity','')}:{f.get('file','')}:{f.get('category','')}:{(f.get('description') or '')[:80]}\" for f in findings)
    return hashlib.md5('|'.join(items).encode(), usedforsecurity=False).hexdigest()[:12]
"
```

## 13. Bugfix History

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

## 14. Pitfalls

1. **Состояние** — в kanban.db. После рестарта — `pipeline_resume()`. state.json НЕ СУЩЕСТВУЕТ.
2. **Ensemble только на round=0/1.** На round 2+ single pass (экономия).
3. **LLM Judge оркестрация** — загружать этот скилл перед каждым ensemble-прогоном. Не из памяти.
4. **judge.prompt удалён** — промпты генерируются программно в `_build_judge_prompt()`.
5. **classify word-boundary** — `len(kw) < 5`, не `<= 5`. Иначе `crash` не матчит `crashes`.
6. **Ruff I001 в try/except** — одна строка на импорт, не многострочный.
7. **scan_board parent order** — всегда `ORDER BY created_at DESC LIMIT 1`.
8. **P1 self-resolve** — исправленный P1 помечай как P2, а то convergence зациклится.
9. **Kanban bypass** — никогда не bypass через прямой delegate_task.
10. **Kanban worker toolsets override** — диспатчер (`_default_spawn` в `kanban_db.py:8307-8309`) читает `_get_platform_tools(cfg, "cli")` из профиля воркера и передаёт как `--toolsets a,b,c`. Это **CLI-флаг высшего приоритета** — переопределяет `enabled_toolsets` в профиле. Решение: `agent.disabled_toolsets` в профиле фильтрует тулзы до того, как диспатчер их запакует.
