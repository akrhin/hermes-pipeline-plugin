---
name: pipeline-orchestrator
description: "Главный оркестратор-скилл for Pipeline Plugin v3.8.4 — kanban.db SSOT, 17 agents, 8 categories, two kanban modes (native/legacy), selective context, LLM Judge ensemble (execute-then-judge), deterministic convergence (now in convergence.py), hot-reload config, forced findings collection, code-review-graph MCP integration."
author: Hermes Agent + Vladimir
category: hermes
tags: [pipeline, orchestrator, ensemble, convergence, kanban, retro, master]
---

# Pipeline Orchestrator v3.8.4 — Главный оркестратор-скилл

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

### АНТИ-BYPASS ПРАВИЛО (железобетонное)

**Запрещено:**
- `terminal("cd ~/git/... && python3 ...")` — любые ручные вызовы pipeline-функций через терминал
- `import kanban` или `import handlers` в `execute_code()` — прямой вызов API без инструментов
- `delegate_task()` без `pipeline_run_agent()` → `pipeline_advance()` — оркестрация только через пайплайн
- Ручной `git status`, `ruff`, `pytest`, `ls` — если задача связана с pipeline-plugin
- Любая проверка состояния плагина через shell вместо pipeline-инструментов

**Как должно быть:**
1. classify → save → run_agent → delegate_task(**call_args) → advance → (повтор для каждого агента)
2. Если `pipeline_save` вернул `null` — использовать `pipeline_clear` + `pipeline_save` снова, не лезть в терминал
3. Все проверки (тесты, ruff, статус) — через агентов пайплайна, не вручную

> 🔴 **Если bypassнул — удали канал и заново. Пользователь прав — бесит.**

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

### Фаза 4: Kanban — два режима (v3.8.4)

Начиная с v3.8.4, kanban.py работает как **роутер** между двумя движками:

| Режим | Движок | Когда использовать |
|-------|--------|-------------------|
| `native` (DEFAULT v3.8.4+) | `subprocess → hermes kanban` CLI (`kanban_adapter.py`) | Интеграция с Hermes kanban UI/дашбордом |
| `legacy` | Прямой SQLite (`kanban_legacy.py` — прямой `sqlite3` API) | Изолированные окружения, без Hermes kanban CLI |

**Роутинг (`kanban_router.py`):**
- `kanban_mode: native` (DEFAULT) → вызовы идут в `kanban_adapter.py` (через `subprocess → hermes kanban` CLI)
- `kanban_mode: legacy` → вызовы идут в `kanban_legacy.py` (прямой SQLite)
- Полная feature parity: `_cleanup_stale_pipelines()`, `_claim_and_assign()`, `block_task()`, lifecycle parent status tracking, `show_task()` enrichment

**Как настроить:**
```yaml
# config.yaml
kanban_mode: native  # или legacy (по умолчанию)
```

> Если `kanban_mode: native`, но Hermes kanban не установлен — плагин падает с понятной ошибкой, а не молча возвращает null.

### Фаза 5: Ensemble-цикл (v3.8.4)

Best-of-N ensemble с LLM Judge:

1. **`pipeline_ensemble_run(state, agent_id, n=3)`** — генерирует N кандидатов (каждый как delegation package)
2. **`pipeline_ensemble_judge(request, candidates, judge_mode='llm')`** — Judge оценивает кандидатов:
   - `judge_mode='llm'`: LLM Judge — сравнивает все кандидаты, выбирает лучший по критериям: корректность, полнота, безопасность, стиль
   - `judge_mode='deterministic'`: фиксированные правила (запасной вариант)
3. Лучший кандидат исполняется как обычный агент
4. В конце — **convergence check** через `pipeline_convergence(state, findings?)`

**Deterministic convergence** (находится в `convergence.py`):
- Анализирует findings: если все `status: fixed` — convergence достигнута
- Если есть открытые findings → новый раунд с @fixer/@coder
- Максимум 3 цикла, после — escalate to user

**Когда использовать ensemble:**
- Сложные задачи (архитектура, безопасность, рефакторинг)
- Когда нужна уверенность в качестве (>1 вариант для сравнения)
- По умолчанию — single agent (без ensemble), ensemble только по требованию

### Фаза 6: Документация (В КОНЦЕ ПРОГОНА, ПЕРЕД ПУШЕМ)
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

### Фаза 7: Скиллы и инструменты (В КОНЦЕ ПРОГОНА)
- [ ] **skill/pipeline-orchestrator/SKILL.md** — если изменилась оркестрация, агенты, конфиг, баги
- [ ] **skill/pipeline-ensemble/SKILL.md** — если ensemble изменился
- [ ] **skill/pipeline-audit-checklist/SKILL.md** — если добавились баги или проверки
- [ ] Синхронизировать symlinks: `~/.hermes/skills/hermes/pipeline-orchestrator` → `~/git/hermes-pipeline-plugin/skill/pipeline-orchestrator`

### Фаза 8: Версионность и релиз (обязательно)

Перед пушем — бамп версии по схеме `v3.X.Y`:

1. **plugin.yaml** — поднять `version:` на следующий номер
2. **CHANGELOG.md** — новая запись с датой, списком изменений (что, почему)
3. **AGENTS.md** — обновить все упоминания версии в таблицах
4. **skill/pipeline-orchestrator/SKILL.md** — обновить версию в заголовке и description
5. **skill/pipeline-ensemble/SKILL.md** — обновить ссылки на версию
6. **skill/pipeline-audit-checklist/SKILL.md** — обновить ссылки на версию
7. **pytest -q** — убедиться что тесты проходят
8. **ruff check .** — убедиться что линтер чист
9. **git add -A && git commit -m "v{X.Y.Z}: краткое описание"**
10. **git tag v{X.Y.Z} && git push origin main --tags**

> ❗ Если изменение затрагивает только один компонент, бамп не нужен. Бамп — про релизный цикл.
> В задаче кандидата укажи `tools/retro-summary.candidate_N` вместо `tools/retro-summary`.
> `N` — номер кандидата (1–5). Так Judge увидит все 5 реализаций, а не только последнюю.