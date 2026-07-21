---
name: pipeline-orchestrator
description: "Главный оркестратор-скилл for Pipeline Plugin v3.8.2 — kanban.db SSOT, 17 agents, 8 categories, selective context, LLM Judge ensemble (execute-then-judge), deterministic convergence (now in convergence.py), hot-reload config, forced findings collection, code-review-graph MCP integration."
author: Hermes Agent + Vladimir
category: hermes
tags: [pipeline, orchestrator, ensemble, convergence, kanban, retro, master]
---

# Pipeline Orchestrator v3.8.2 — Главный оркестратор-скилл

## ⚠️ ПРАВИЛА РАБОТЫ С ПРОЕКТОМ (читать ПЕРЕД КАЖДЫМ ПРОГОНОМ)

**Этот раздел — закон. Не пропускай ни один пункт, не говори "потом", не оставляй todo в ответах.**

### 0. КРАТКО О БЕСПОКОЙНОСТИ (важно для скорости)
- Читаю скилл ТОЛЬКО перед тем, как начать. Во время работы не читаю повторно.
- Если тебе что-то непонятно в правиле — спрашивай, но без лишних деталей.
- Всегда одно действие в одном сообщении. После завершения отвечаю только с итоговым результатом.

### 1. Получение задачи → Декомпозиция
0. **ПЕРЕД ВСЕМ:** Загрузи этот скилл (`skill_view('pipeline-orchestrator')`) — перечитай правила, не по памяти.
1. Прочитай README.md, AGENTS.md, ARCHITECTURE.md, CHANGELOG.md, plugin.yaml
2. Узнай текущую версию, что уже сделано, кто авторы
3. Разбей задачу на шаги. Запиши в todo. Не начинай исполнение без плана.

### Правило 0: Проверка активного pipeline при старте
**ВСЕГДА при старте сессии (после /new, /clear, рестарта):**
1. Вызови `pipeline_resume()` — если есть активный пайплайн, подхвати его
2. Вызови `skill_view('pipeline-orchestrator')` — загрузи этот скил
3. Если `pipeline_resume()` вернул стейт — продолжай с того же места (не начинай новый)
4. Сохрани в Mnemosyne факт о старте: mnemosyne_remember(content="Pipeline session started", source="lifecycle", scope="session")

### Фаза 2: Исполнение
4. Работай через pipeline: classify → save → load/resume → advance
5. Не bypass kanban — ни одного прямого `delegate_task` вне пайплайна
6. Каждые 5-7 вызовов инструментов — промежуточный вердикт: что сделано, что дальше

7. **Точный шаблон вызова агента через pipeline (v3.8.2):**
   ```
   pkg = pipeline_run_agent(state, 'agent_name')
   delegate_task(**pkg.call_args)  # call_args = {'goal': prompt} — только goal, всё остальное в промпте
   pipeline_advance(state, 'agent_name')
   ```

8. **Fix #2 call_args bypass (v3.8.2):**
   - `handle_run_agent()` возвращает `call_args = {'goal': prompt}` — больше нет `{prompt, provider, model, description}` в call_args
   - `build_judge_call_args()` в ensemble.py: то же — `{'goal': prompt}`
   - **Почему:** оркестратор получает промпт через `call_args.goal`, а не через разрозненные поля. Меньше путаницы, чище контракт.
   - **Важно:** не добавляй лишних полей в call_args — всё, что нужно агенту, должно быть в самом промпте.

### Фаза 3: Quality Gates (автоматически)
Все 17 агентов работают через `delegate/polza/deepseek-v4-flash` (@security — `delegate/deepseek-v4-pro`).

- **@quality** агент запускается в конце пайплайна для BUG_KNOWN, BUG_UNKNOWN, REFACTORING, FEATURE
- Если @quality вернул FAIL — идёт новый раунд с @fixer/@coder
- CI-гейты: ruff → bandit → compileall → pytest

### Фаза 4: Документация (В КОНЦЕ ПРОГОНА, ПЕРЕД ПУШЕМ)
- [ ] **Форматирование ответов:** загрузи skills `response-formatting` + `telegram-rich-formatting` перед финальным ответом
- [ ] Для таблиц используй pipe-синтаксис (`| Header |`), не bullet-списки
- [ ] **Проверка качества перед пушем (если проект Python):**
  - `ruff check .` — линтер
  - `bandit -r . -ll` — SAST
  - `python -m compileall .` — синтаксис
  - `python -m pytest -q` — тесты

> ❗ Обновить ВСЕ эти файлы, если задача их затрагивает:
> - [ ] **plugin.yaml** — версия, описание
> - [ ] **CHANGELOG.md** — новая запись с датой, список изменений (что, почему, кем)
> - [ ] **AGENTS.md** — агенты, промпты, таблица категорий
> - [ ] **ARCHITECTURE.md** — миграция v?.?.? в таблице истории
> - [ ] **ARCHITECTURE-FIXES.md** — если фиксил баги
> - [ ] **CONTRIBUTORS.md** — если работал с чужим PR
> - [ ] **README.md** — если изменился quick start, установка, требования

### Фаза 4: Скиллы и инструменты (В КОНЦЕ ПРОГОНА)
- [ ] **skill/pipeline-orchestrator/SKILL.md** — если изменилась оркестрация, агенты, конфиг, баги
- [ ] **skill/pipeline-ensemble/SKILL.md** — если ensemble изменился
- [ ] **skill/pipeline-audit-checklist/SKILL.md** — если добавились баги или проверки
- [ ] Синхронизировать symlinks: `~/.hermes/skills/hermes/pipeline-orchestrator` → `~/git/hermes-pipeline-plugin/skill/pipeline-orchestrator`

> ⚠️ **Hotfix для execute-then-judge:** каждому кандидату — уникальный output-файл.
> В задаче кандидата укажи `tools/retro-summary.candidate_N` вместо `tools/retro-summary`.
> `N` — номер кандидата (1–5). Так Judge увидит все 5 реализаций, а не только последнюю.