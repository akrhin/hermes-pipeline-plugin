---
name: pipeline-ensemble
description: "Best-of-N ensemble — thin reference to pipeline-orchestrator (master skill)"
author: Hermes Agent
category: hermes
tags: [pipeline, ensemble, reference]
---

# Pipeline Ensemble

**Весь контент перенесён в master skill `pipeline-orchestrator` (секции 3-5, 11).**

Используй:

```
skill_view('pipeline-orchestrator')
```

### Быстрые ссылки

- LLM Judge оркестрация → pipeline-orchestrator раздел 4
- Ensemble вариации → pipeline-orchestrator раздел 5
- Багфиксы → pipeline-orchestrator раздел 9
- Pitfalls → pipeline-orchestrator раздел 10

### Key files

| Файл | Назначение |
|------|-----------|
| `ensemble.py` | generate_candidates, judge_candidates, build_judge_prompt |
| `__init__.py` | handle_ensemble_run, handle_ensemble_judge |
| `tests/test_ensemble.py` | 3 regression tests |
