---
name: pipeline-ensemble
description: "Best-of-N ensemble — thin reference to pipeline-orchestrator (master skill)"
author: Hermes Agent
category: hermes
tags: [pipeline, ensemble, reference]
---

# Pipeline Ensemble

**Краткое описание:** Вся документация и реализация объединена в `pipeline-orchestrator/SKILL.md` (секции 3-5, 11).

## Как использовать
Стандартный вызов:
```
skill_view('pipeline-orchestrator')
```

## Основные ссылки
- ОптимизацияENSEMBLE → pipeline-orchestrator раздел 5
- Реализация YESD/NOB → pipeline-orchestrator раздел 9
- Проблемы → pipeline-orchestrator раздел 10

## Файлы в репозитории
| Файл | Назначение |
|------|-----------
| `ensemble.py` | Функции: generate_candidates, judge_candidates, build_judge_prompt |
| `__init__.py` | Хендлеры: handle_ensemble_run, handle_ensemble_judge |
| `tests/test_ensemble.py` | Регрессионные тесты (3 штуки) |

## Изменения 2026-07-21 (v3.8.2)
1. **`llm_judge_candidates()`** — замена `delegate_task`-базированных вызовов на `ctx.llm.complete()`
2. **Fallback** — детермистический джудж в случае недоступности контекста
3. **Формат файлов кандидатов** — `tools/retro-summary.candidate_N` для каждого кандидата
4. **Fix #2: build_judge_call_args** — теперь чисто `{'goal': prompt}` вместо `{prompt, config}`. Убран unused param `config`.
5. **Делегация Judge** — `handle_ensemble_judge` передаёт `judge_call_args` с единственным полем `goal`
6. **Тесты:** 311 passed (+35 новых test_delegation_contract.py на call_args.goal == prompt)

## Пользовательские требования
- Все `/pipeline run ensemble` должны ссылаться на уникальные файлы кандидатов
- Агенты должны использовать паттерн `candidate_N` в реализации

## Тестирование требуется
1. `pytest test_ensemble.py` — проверка обработки файлов
2. Тест с `ctx=None` — проверка fallbacks