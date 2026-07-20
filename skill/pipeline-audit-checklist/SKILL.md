---
name: pipeline-audit-checklist
description: "Verification checklist for Pipeline Plugin v3.3.3 — comprehensive audit covering orchestrator, ensemble, docs, retro"
author: Hermes Agent
category: verification
tags: [pipeline, audit, verification, quality, ensemble, master]
---

# Pipeline Audit Checklist (v3.3.4)

## Preconditions
- [ ] Load `pipeline-orchestrator` skill (`skill_view('pipeline-orchestrator')`)
- [ ] `hermes plugins list` shows `pipeline` as enabled
- [ ] `~/.hermes/plugins/pipeline/config.yaml` — валидный конфиг
- [ ] 79/79 тестов проходят (`pytest tests/ -q`)

## Known Bugfixes (v3.3.4 — 28 total)

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
| **v3.3.4** | — | **README** | **Установка: устаревшие 2 строки, мёртвые kanban CLI команды** | ✅ |

## Audit Steps

### 1. Context Selectivity Check
- [ ] `AGENT_CONTEXT_FIELDS` в `__init__.py` — каждый агент с конкретными секциями
- [ ] Никто не получает `full_context` без необходимости

### 2. Ensemble Functionality
- [ ] `pipeline/ensemble/enabled: true` в config.yaml
- [ ] `pipeline_ensemble_judge` — winner_id: null + judge_call_args (bug #3 fix)
- [ ] **Critical: LLM Judge оркестрация** — `delegate_task(**judge_call_args)` перед использованием winner_id
- [ ] Cost optimization: ensemble off на round >= 2

### 3. Model Routing
- [ ] security → delegate/deepseek-v4-pro, все остальные → direct/deepseek-v4-flash
- [ ] Hot-reload config

### 4. Documentation
- [ ] **README.md** — v3.3.4, установка в 5 шагов, без мёртвых kanban CLI команд
- [ ] **AGENTS.md** — v3.3.3, all 16 agents, per-category table
- [ ] **ARCHITECTURE.md** — migration history includes v3.3.3
- [ ] **plugin.yaml** — version: 3.3.4
- [ ] **CHANGELOG.md** — все версии, включая v3.3.4
- [ ] **CODE_OF_CONDUCT.md** — существует
- [ ] **CONTRIBUTING.md** — существует
- [ ] **SECURITY.md** — существует
- [ ] .github/ISSUE_TEMPLATE/ — bug_report.yml + feature_request.yml
- [ ] .github/PULL_REQUEST_TEMPLATE.md — существует

### 5. Tests
- [ ] 79/79 passed
- [ ] Ruff: 0 errors
- [ ] 14 classify tests pass
- [ ] 3 ensemble tests pass

## Success Criteria
- **79/79 tests**, 0 lint
- **ALL 16 agents** get real prompt (not null)
- **LLM Judge** returns winner_id=null + judge_call_args; orchestrator calls delegate_task
- **No P0/P1 findings** in convergence
- **5 unused agents** (debugger, devops, fixer, optimizer, refactorer) have real prompts
- **README** has correct 5-step install (no dead kanban CLI commands)

## References
- Master skill: `skill_view('pipeline-orchestrator')`
- Pipeline repo: `~/git/hermes-pipeline-plugin`
