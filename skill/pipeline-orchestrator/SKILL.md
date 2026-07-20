---
name: pipeline-orchestrator
description: "Главный оркестратор-скилл for Pipeline Plugin v3.6.0 — kanban.db SSOT, 16 agents, 8 categories, selective context, LLM Judge ensemble (execute-then-judge), deterministic convergence, hot-reload config, forced findings collection, code-review-graph MCP integration (38-528× token savings)."
author: Hermes Agent + Vladimir
category: hermes
tags: [pipeline, orchestrator, ensemble, convergence, kanban, retro, master]
---

# Pipeline Orchestrator v3.6.0 — Главный оркестратор-скилл

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

> ⚠️ **Hotfix для execute-then-judge:** каждому кандидату — уникальный output-файл.
> В задаче кандидата укажи `tools/retro-summary.candidate_N` вместо `tools/retro-summary`.
> `N` — номер кандидата (1–5). Так Judge увидит все 5 реализаций, а не только последнюю.

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
     │
     ├─ @reviewer → дополнительно вызывает
     │   mcp_code_review_graph_get_review_context_tool
     │
     ├─ @security → дополнительно вызывает
     │   mcp_code_review_graph_get_review_context_tool
     │
     └─ остальные → как обычно
                 
     pipeline_advance(state, agent) → promote next
                      ↓
              ╔══════════════════════════════════╗
              ║ СБОР FINDINGS после каждого      ║
              ║ reviewer/tester → push в findings ║
              ╚══════════════════════════════════╝
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

## 3. Pipeline Loop (псевдокод — точный порядок действий)

```
state = pipeline_resume() or pipeline_save({category, request, pipeline})

for each agent in state["pipeline"]:
    state = pipeline_advance(state, current_agent)

    if agent == "coder" and state["round"] <= 1 and ensemble_enabled:
        # ═══ ENSEMBLE FLOW (FIXED v3.5.0) ═══════════════════════
        # 1. Генерация кандидатов (описания)
        candidates = pipeline_ensemble_run(state, "coder", n=5)
        
        # 2. ВЫПОЛНЕНИЕ кандидатов ДО judge — каждый в свой файл
        for c in candidates:
            # ⚠️ Каждому кандидату — уникальный output-файл, иначе перезапись!
            candidate_task = c["task"].replace("tools/retro-summary", f"tools/retro-summary.{c['id']}")
            c["task"] = candidate_task
            result = delegate_task(goal=candidate_task, context=c["context"])
            c["output"] = result["summary"]
        
        # 3. ТЕПЕРЬ judge оценивает КОД (не описания)
        judge_result = pipeline_ensemble_judge({
            "request": request,
            "candidates": candidates,  # ← с полем output!
            "judge_mode": "llm"
        })
        
        # 4. Вызов LLM Judge
        if judge_result.get("judge_call_args"):
            llm_response = delegate_task(**judge_result["judge_call_args"])
            parsed = json.loads(llm_response)
            winner_id = parsed.get("winner_id", "candidate_3")
    else:
        # === SINGLE PASS ===
        pkg = pipeline_run_agent(state, agent)
        if pkg["directive"] == "delegate":
            result = delegate_task(**pkg["call_args"])
        else:
            result = <execute prompt directly in context>
    
    # ═══ СБОР FINDINGS ═══════════════════════
    findings = state.get("findings", [])
    if agent in ("reviewer", "tester", "security", "integration"):
        # Парсим вывод агента на предмет [P0], [P1], [P2]
        new_findings = extract_findings_from_output(result)
        if new_findings:
            findings.extend(new_findings)
            state["findings"] = findings

# После цикла — конвергенция
if findings:
    conv = pipeline_convergence(state, findings)
```

**Ключевое:** после каждого `reviewer`/`tester`/`security` ПАРСИТЬ их вывод на предмет findings. Иначе convergence не увидит ничего и решит converged.

---

## 4. LLM Judge Orchestration (v3.5.0 — execute-then-judge)

### Правильная последовательность

```python
# ШАГ 1: Генерация кандидатов
candidates_result = pipeline_ensemble_run({
    "state": state,
    "agent_id": "coder",
    "n": 5
})
candidates = candidates_result["candidates"]

# ШАГ 2: Исполнение КАЖДОГО кандидата до judge — в СВОЙ файл!
for c in candidates:
    # ⚠️ Уникальный файл на кандидата, иначе последний перезапишет всех
    candidate_task = c["task"].replace(
        "tools/retro-summary",
        f"tools/retro-summary.{c['id']}"
    )
    c["task"] = candidate_task
    c["output"] = delegate_task(
        goal=candidate_task,
        context=c.get("context", {})
    )["summary"]

# ШАГ 3: Оценка judge с реальным кодом
judge_result = pipeline_ensemble_judge({
    "request": state["request"],
    "candidates": candidates,   # содержит output[]
    "judge_mode": "llm"
})

# ШАГ 4: Если LLM mode — делегировать судье
if judge_result.get("judge_call_args"):
    llm_response = delegate_task(**judge_result["judge_call_args"])
    parsed = json.loads(llm_response)
    winner_id = parsed.get("winner_id", "candidate_3")
    rationale = parsed.get("rationale", "")
    scores = parsed.get("scores", [])
else:
    winner_id = judge_result.get("winner_id", "candidate_3")
```

### Judge modes

| Mode | Поведение |
|------|-----------|
| **deterministic** | Picks middle candidate (len//2). Returns `winner_id: candidate_3`. |
| **llm** | Returns `winner_id: null, judge_call_args: {...}`. Orchestrator calls `delegate_task`. |

---

## 5. Сбор Findings (CRITICAL — иначе convergence = converged всегда)

После каждого агента, который может найти баги (reviewer, tester, security, integration), **парсить его вывод**.

### Формат findings

Каждый finding — dict с полями:
```python
{
    "severity": "P0" | "P1" | "P2",
    "file": "path/to/file.py",       # или "general" если без файла
    "category": "security" | "style" | "logic" | "coverage" | "performance" | ...,
    "description": "что именно не так",
    "recommendation": "как исправить",
    "status": "open"                  # open/fixed/accepted
}
```

### Как парсить вывод агента

Агент **обязан** в своём выводе указывать findings в формате:
```
[P0] file.py: описание — рекомендация
[P1] file.py: описание — рекомендация
[P2] general: описание — рекомендация
```

Если агент не нашёл проблем — findings пуст. Это нормально (converged).

```python
def extract_findings_from_output(output: str) -> list[dict]:
    """Парсинг [P0], [P1], [P2] из вывода агента."""
    import re
    findings = []
    for sev in ("P0", "P1", "P2"):
        pattern = rf"\[{sev}\]\s+(\S+):\s*(.+?)(?:\s*—\s*(.+))?$"
        for match in re.finditer(pattern, output, re.MULTILINE):
            findings.append({
                "severity": sev,
                "file": match.group(1),
                "description": match.group(2).strip(),
                "recommendation": (match.group(3) or "").strip(),
                "status": "open",
                "category": "review",
            })
    return findings
```

Обязательно побеждать findings в `state["findings"]` перед вызовом `pipeline_convergence`.

---

## 6. Ensemble Variations

| ID | T | Strategy |
|----|---|----------|
| candidate_1 | 0.3 | Минимальные изменения |
| candidate_2 | 0.5 | Чистый код с type hints |
| candidate_3 | 0.7 | Standard production |
| candidate_4 | 0.9 | Полное решение с тестами |
| candidate_5 | 1.1 | Нестандартный подход |

---

## 7. Convergence Engine (deterministic)

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

## 8. Config

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

## 9. 12 Pipeline Tools + MCP-инструменты CRG

### Pipeline Tools (12 шт)

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

### MCP-инструменты code-review-graph

Доступны агентам @reviewer и @security (появляются после `/new`):

| MCP Tool | Prefix | Назначение |
|----------|--------|------------|
| `mcp_code_review_graph_get_review_context_tool` | `mcp_code_review_graph_` | Blast radius, risk score, affected flows, test gaps |
| `mcp_code_review_graph_get_impact_radius_tool` | `mcp_code_review_graph_` | Детальный разбор затронутых функций |
| `mcp_code_review_graph_query_graph_tool` | `mcp_code_review_graph_` | Точечный запрос: callers_of, callees_of, tests_for, file_summary |
| `mcp_code_review_graph_list_graph_stats_tool` | `mcp_code_review_graph_` | Статистика графа (узлы, рёбра, файлы) |
| `mcp_code_review_graph_build_or_update_graph_tool` | `mcp_code_review_graph_` | Пересборка графа |

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

---

## 11. Python Plugin Gotchas

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

### P1 findings — self-resolve
Если нашёл и исправил P1 в том же раунде — **помечай как P2**, а не P1. Иначе:
- severity=P1 → convergence видит «1 P1 остался» → continue
- severity=P2 → convergence видит 0 P0/P1 → converged

### Context-mode для анализа больших кодбаз
Не тащи 10+ файлов `read_file` + reasoning в контекст. Используй `execute_code()`.

---

## 12. Retro Log Analysis

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

# Findings по прогону
cat ~/.hermes/plugins/pipeline/retro/pipe_*.jsonl | python3 -c "
import sys,json
for line in sys.stdin:
    e = json.loads(line)
    if e.get('event') == 'findings_detail':
        print(f\"{e.get('run','')[:20]} → {len(e.get('items',[]))} findings\")
        for f in e.get('items',[]):
            print(f\"  [{f.get('severity','?')}] {f.get('file','?')}: {f.get('description','')[:80]}\")
"
```

---

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
| v3.3.3 | — | _orchestration_ | **LLM Judge: delegate_task с judge_call_args** | ✅ |
| **v3.5.0** | — | kanban.py | **scan_board order fix** — парсинг pipeline из parent body | ✅ |
| **v3.5.0** | — | ensemble.py | **Judge output 2000→8000** — реальный код для оценки | ✅ |
| v3.5.0 | — | __init__.py | **Judge config passthrough fix** | ✅ |
| **v3.6.0** | — | agents/*.prompt | **CRG integration**: @reviewer/@security используют MCP-инструменты code-review-graph | ✅ |

## 15. Pitfalls (обновлено v3.6.0)

1. **Состояние** — в kanban.db. После рестарта — `pipeline_resume()`. state.json НЕ СУЩЕСТВУЕТ.
2. **Ensemble только на round=0/1.** На round 2+ single pass (экономия).
3. **LLM Judge оркестрация** — загружать этот скилл перед каждым ensemble-прогоном. Не из памяти.
4. **judge.prompt удалён** — промпты генерируются программно в `_build_judge_prompt()`.
5. **classify word-boundary** — `len(kw) < 5`, не `<= 5`. Иначе `crash` не матчит `crashes`.
6. **Ruff I001 в try/except** — одна строка на импорт, не многострочный.
7. **scan_board parent order** — в v3.5.0 парсинг из body, не ORDER BY.
8. **P1 self-resolve** — исправленный P1 помечай как P2, а то convergence зациклится.
9. **Kanban bypass** — никогда не bypass через прямой delegate_task.
10. **Findings collection** — КРИТИЧЕСКИ ВАЖНО парсить вывод reviewer/tester/security на [P0/P1/P2]. Без этого convergence всегда converged.
11. **Execute-then-judge file overwrite** — каждый делегированный кандидат пишет в один и тот же `tools/retro-summary`. Последний перезаписывает всех. **Фикс:** в задаче кандидата заменить `tools/retro-summary` на `tools/retro-summary.{candidate_id}`. Сделать ДО вызова `delegate_task`.
12. **Kanban worker toolsets override** — диспатчер читает `_get_platform_tools(cfg, "cli")` из профиля воркера и передаёт как `--toolsets a,b,c`. Это CLI-флаг высшего приоритета — переопределяет `enabled_toolsets` в профиле. Решение: `agent.disabled_toolsets` в профиле фильтрует тулзы до того, как диспатчер их запакует.
13. **CRG MCP-сервер требует `/new`** — после добавления/изменения MCP-сервера в конфиге нужен рестарт сессии. Сам плагин (pipeline) хот-релоадит конфиг, но MCP-серверы поднимаются при старте Hermes.
14. **CRG граф — под один проект** — `code-review-graph mcp --repo <path>` включает только один репозиторий. Для работы с разными проектами нужно менять `--repo` в конфиге и делать `/new`, либо запускать отдельные инстансы daemon.
15. **CRG без igraph** — если не установлен `igraph`, community detection использует file-based fallback (менее точный). Для плагина это не критично — достаточно для blast radius.
