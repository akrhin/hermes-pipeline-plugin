# Pipeline Plugin — Development Plan

## Текущее состояние
- **Версия:** v3.7.2-dev
- **Ветка:** dev (прототип — не тегировать)
- **Статус:** 112/112 тестов, Ruff 0

## Очередь разработки (приоритет)

### 🔴 P1 — Сейчас ✅

| # | Задача | Тип | Описание | Статус |
|---|--------|-----|----------|--------|
| 1 | Slash-команда `/pipeline` | feature | `ctx.register_command()` — status, show, clear в чате | ✅ |
| 2 | CLI-команда `hermes pipeline` | feature | `ctx.register_cli_command()` — то же в терминале | ✅ |
| 3 | `check_fn` для инструментов | perf | Скрывать `pipeline_ensemble_run`/`pipeline_ensemble_judge`, если ensemble выключен | ✅ |

### 🟡 P2 — Скоро ✅

| # | Задача | Тип | Описание | Статус |
|---|--------|-----|----------|--------|
| 4 | `lazy_singleton` для retro | refactor | _SingletonSlot — thread-safe, double-checked locking | ✅ |
| 5 | `pre_tool_call` хук метрик | feature | _on_pre_tool_call — считает pipeline_* + agent_* вызовы | ✅ |
| 6 | `requires_env` в plugin.yaml | docs | Пустой блок для формального соответствия | ✅ |

### 🟢 P3 — Когда-нибудь

| # | Задача | Тип | Описание | Статус |
|---|--------|-----|----------|--------|
| 7 | UX — прогресс-бар, emoji, @documenter-отчёты | feature | classify.emoji + _render_pipeline_status с прогресс-баром | ✅ |
| 8 | `dispatch_tool` из slash-команд | feature | Из `/pipeline run <tool>` запускать pipeline инструменты | ✅ |
| 9 | `ctx.llm` для ensemble judge | arch | LLM-фасад хоста вместо delegate_task через `llm_judge_candidates()` | ✅ |
| 10 | `register_auxiliary_task` для classify | arch | Выделить классификатор в настраиваемую подзадачу | |

## Процесс
1. Берём задачу из P1
2. Создаём канбан-таск в пайплайне
3. Проходим агентов (finder → ... → documenter)
4. Тесты + пуш в dev
5. Обновляем PLAN.md
