---
name: pipeline-audit-checklist
description: "Verification Checklist for Pipeline Plugin v3.8.2 — comprehensive audit covering orchestrator, ensemble, docs, retro, code-review-graph, @quality gates, dead code cleanup"
author: Hermes Agent
category: hermes
tags: [pipeline, audit, verification, quality, ensemble, master]
---

# Pipeline Audit Checklist (v3.8.2)

## Preconditions
- [ ] **ПЕРВЫМ ДЕЛОМ:** Load `pipeline-orchestrator` skill (`skill_view('pipeline-orchestrator')`)
- [ ] `hermes plugins list` shows `pipeline` as enabled
- [ ] `~/.hermes/plugins/pipeline/config.yaml` — валидный конфиг
- [ ] **311/311 тестов проходят** (`pytest tests/ -q`)
- [ ] code-review-graph installed (`code-review-graph --version`) — v2.3.7+
- [ ] CRG MCP-сервер в `~/.hermes/config.addon.yaml` с `enabled: true`
- [ ] Граф собран (`code-review-graph status` в корне проекта)
- [ ] Dead code не осталось — `ruff check .` чистый

## Критические проверки (v3.8.2)

### dead code removal
- [ ] `kanban.py::generate_candidates`, `kanban.py::judge_candidates` — удалены (дубли из `ensemble.py`)
- [ ] Ruff 0 errors — 10× F821 устранены

### scan_board order fix
- [ ] `pipeline_resume()` возвращает правильный порядок агентов (из parent body, не ORDER BY)
- [ ] В родительском body есть строка «Агенты: @finder → @analyst → ...»

## Known Bugfixes (v3.4.0–v3.8.2 — 32 total)

| ID | Sev | File | Баг | Статус |
|----|-----|------|-----|--------|
| #1 | P1 | kanban.py | reopen() не существовал | ✅ |
| #3 | **P0** | ensemble.py | LLM Judge — заглушка (всегда candidate_3) | ✅ |
| #4 | **P0** | __init__.py | Flash-агенты без prompt (null) | ✅ |
| #10 | P2 | integration.prompt | Мёртвый Full context | ✅ |
| #11 | P2 | kanban.py | maxed_out не закрывал детей | ✅ |
| #15 | P1 | kanban.py | stale cleanup пропускал 1-child | ✅ |
| #20 | P2 | kanban.py | scan_board без LIMIT 1 | ✅ |
| v3.3.2 | — | classify.py | RU keywords, word-boundary, priority | ✅ |
| v3.3.3 | — | orchestration | LLM Judge: delegate_task с judge_call_args | ✅ |
| **v3.5.0** | — | **README** | **scan_board order fix + Judge output 8000 + config passthrough** | ✅ |
| **v3.5.0** | — | **ensemble flow** | **execute-then-judge + findings collection (оркестрация)** | ✅ |
| **v3.8.1** | — | **pipeline** | **@quality gates не запускались до пуша** | ✅ |
| **v3.8.1** | — | **pipeline** | **Потеря контекста после рестарта — persona permanent auto-resume** | ✅ |
| **v3.8.2** | — | **kanban.py** | **Dead code — generate_candidates/judge_candidates дубли (10× F821)** | ✅ |
| **v3.8.2** | — | **models** | **Модели fix — все Flash-агенты на delegate/polza/deepseek-v4-flash** | ✅ |
| **v3.8.2 (fix #1)** | P1 | **kanban.py** | **threading.local() → модульная переменная, проверка живости SELECT 1** | ✅ |
| **v3.8.2 (fix #2)** | P1 | **handlers/__init__.py** | **call_args = {'goal': prompt} — упрощение контракта делегации** | ✅ |
| **v3.8.2 (fix #3)** | — | **tests/** | **35 новых тестов на контракт call_args + delegation contract** | ✅ |
| **v3.8.2 (P1)** | P1 | **handlers/__init__.py** | **@quality не было в AGENT_CONTEXT_FIELDS** | ✅ |
| **v3.8.2 (P1)** | P1 | **kanban.py** | **_close_connection() не вызывался в on_clear()** | ✅ |
| **v3.8.2 (P1)** | P1 | **retro.py** | **DEFAULT_RETRO_CONFIG auto_analyze: False → True** | ✅ |
| **v3.8.2 (P2)** | P2 | **kanban.py** | **Unused params: promote(force), complete(metadata), block_task(reason)** | ✅ |
| **v3.8.2 (P2)** | P2 | **retro.py** | **Unused param run_context в build_analysis_prompt()** | ✅ |
| **v3.8.2 (P2)** | P2 | **ensemble.py** | **Unused param config в build_judge_call_args()** | ✅ |
| **v3.8.2 (P2)** | P2 | **handlers/__init__.py** | **threading.Lock() для _MODEL_MAP_CACHE** | ✅ |

## Audit Steps

### 1. Context Selectivity Check
- [ ] `AGENT_CONTEXT_FIELDS` в `__init__.py` — каждый агент с конкретными секциями
- [ ] Никто не получает `full_context` без необходимости

### 2. Ensemble Functionality
- [ ] `pipeline/ensemble/enabled: true` в config.yaml
- [ ] `pipeline_ensemble_judge` — winner_id: null + judge_call_args (bug #3 fix)
- [ ] **Critical: LLM Judge оркестрация** — `delegate_task(**judge_call_args)` перед использованием winner_id
- [ ] Cost optimization: ensemble off на round >= 2

### 3. Model Routing (v3.8.2)
- [ ] Все 17 агентов через `delegate_task`
- [ ] security → delegate/deepseek-v4-pro, все остальные → delegate/polza/deepseek-v4-flash
- [ ] Hot-reload config

### 4. Documentation
- [ ] **AGENTS.md** — v3.8.2, all 17 agents, per-category table
- [ ] **ARCHITECTURE.md** — migration history includes v3.8.2
- [ ] **plugin.yaml** — version: 3.8.2
- [ ] **CHANGELOG.md** — все версии, включая v3.8.2
- [ ] **CODE_OF_CONDUCT.md** — существует
- [ ] **CONTRIBUTING.md** — существует
- [ ] **SECURITY.md** — существует
- [ ] .github/ISSUE_TEMPLATE/ — bug_report.yml + feature_request.yml
- [ ] .github/PULL_REQUEST_TEMPLATE.md — существует

### 5. Tests
- [ ] **311/311 passed** (v3.8.2: +199 новых)
- [ ] Ruff: 0 errors
- [ ] 14 classify tests pass
- [ ] 35+ ensemble + delegation contract tests pass

## Success Criteria
- **311/311 tests**, 0 lint
- **ALL 17 agents** get real prompt (not null)
- **All agents via delegate_task** — никаких прямых direct вызовов
- **Dead code removed** — ruff 0 errors, no F821
- **LLM Judge** returns winner_id=null + judge_call_args; orchestrator calls delegate_task
- **No P0/P1 findings** in convergence
- **5 unused agents** (debugger, devops, fixer, optimizer, refactorer) have real prompts

## References
- Master skill: `skill_view('pipeline-orchestrator')`
- Pipeline repo: `~/git/hermes-pipeline-plugin`
