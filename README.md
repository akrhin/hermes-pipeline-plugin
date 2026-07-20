# 🔱 Hermes Pipeline Plugin

> Multi-agent orchestrator for [Hermes Agent](https://github.com/NousResearch/hermes-agent).
> Автоматически разбивает сложные задачи на этапы, запускает специализированных агентов, проверяет качество — и так до 3 раундов, пока не сойдётся.

[![Tests](https://github.com/akrhin/hermes-pipeline-plugin/actions/workflows/test.yml/badge.svg)](https://github.com/akrhin/hermes-pipeline-plugin/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## Как это работает

```
Ты: "добавь JWT аутентификацию в проект"
  │
  ▼
Агент анализирует → срабатывает триггер SECURITY_RELATED
  │
  ▼
Запускается пайплайн из 11 агентов:
  @finder → @analyst → @researcher → @architect → @planner
  → @coder → @reviewer → @security → @integration → @tester → @documenter
  │
  ▼
Каждый агент делает свою часть работы.
  ├─ Flash (direct) — в моём контексте: finder, coder, tester… (15 из 16)
  └─ Pro (delegate) — через сабагента: только security (deepseek-v4-pro)
  │
  ▼
Конвергенция: reviewer/security/tester находят баги → coder исправляет → повтор
  ├─ P0/P1 нет → converged, финал
  ├─ P0/P1 есть → ещё раунд (макс 3)
  ├─ Те же баги второй раз → stuck (нужен человек)
  └─ 3 раунда → maxed_out (hard stop)
```

Плагин даёт инструменты. Оркестрацию делаю я — через скилл `pipeline-orchestrator`.

**Никаких ручных команд.** Просто напиши задачу — пайплайн запустится сам.

---

## Установка

Два компонента: плагин (инструменты) + скилл (оркестрация).

```bash
# 1. Склонировать репозиторий
cd ~
git clone https://github.com/akrhin/hermes-pipeline-plugin.git git/hermes-pipeline-plugin

# 2. Подключить плагин (симлинк)
ln -sf ~/git/hermes-pipeline-plugin ~/.hermes/plugins/pipeline

# 3. Подключить скилл-оркестратор
ln -sf ~/git/hermes-pipeline-plugin/skill/pipeline-orchestrator \
      ~/.hermes/skills/hermes/pipeline-orchestrator

# 4. Включить плагин в конфиге ~/.hermes/config.yaml
```

```yaml
# ~/.hermes/config.yaml
plugins:
  enabled:
    - pipeline
```

```bash
# 5. Создать kanban-доску (один раз)
hermes kanban boards create pipeline "Pipeline tasks"
hermes kanban boards switch pipeline

# 6. Перезагрузить
systemctl --user restart hermes-gateway
```

Готово. Просто пиши задачи — пайплайн запустится автоматически.

---

## Все 16 агентов и их модели

| Агент | Тип | Режим | Дефолтная модель | Что делает |
|-------|-----|-------|-----------------|------------|
| **@finder** | Flash | `direct` | `deepseek-v4-flash` | Разведка: структура, файлы, зависимости |
| **@analyst** | Flash | `direct` | `deepseek-v4-flash` | Диагностика: корень проблемы, логические ошибки |
| **@researcher** | Flash | `direct` | `deepseek-v4-flash` | Поиск best practices и документации |
| **@architect** | Flash | `direct` | `deepseek-v4-flash` | Проектирование решения |
| **@planner** | Flash | `direct` | `deepseek-v4-flash` | Декомпозиция на задачи |
| **@coder** | Flash | `direct` | `deepseek-v4-flash` | Написание кода |
| **@fixer** | Flash | `direct` | `deepseek-v4-flash` | Исправление известных багов |
| **@refactorer** | Flash | `direct` | `deepseek-v4-flash` | Рефакторинг без изменения поведения |
| **@reviewer** | Flash | `direct` | `deepseek-v4-flash` | Код-ревью |
| **@security** | **Pro** | **`delegate`** | **`deepseek-v4-pro`** | Аудит безопасности (только SECURITY_RELATED) |
| **@integration** | Flash | `direct` | `deepseek-v4-flash` | Кросс-файловая консистентность |
| **@tester** | Flash | `direct` | `deepseek-v4-flash` | Написание и прогон тестов |
| **@debugger** | Flash | `direct` | `deepseek-v4-flash` | Отладка (только BUG_UNKNOWN) |
| **@documenter** | Flash | `direct` | `deepseek-v4-flash` | Документация |
| **@devops** | Flash | `direct` | `deepseek-v4-flash` | Инфраструктура (только INFRASTRUCTURE) |
| **@optimizer** | Flash | `direct` | `deepseek-v4-flash` | Оптимизация (только PERFORMANCE) |

**Два режима выполнения:**
- **Flash** (`direct`) — агент работает прямо в моём контексте. Быстро, дёшево. Подходит для механической работы.
- **Pro** (`delegate`) — я поручаю задачу сабагенту через `delegate_task`. Дороже, но качественнее. Используется только для security-аудита.

> **Примечание:** по умолчанию все агенты — Flash. Security переведён на Pro через конфиг (см. ниже).
> Файлы `.prompt` есть для всех 16 агентов. Без файла — генерируется default prompt из AGENT_CONTEXT_FIELDS.

---

## Категории пайплайнов

| Категория | Пайплайн | Примеры запросов |
|-----------|----------|-----------------|
| **SECURITY_RELATED** | finder → analyst → researcher → architect → planner → coder → reviewer → **security** → **integration** → tester → documenter | «добавь JWT», «проверь на уязвимости», «сделай авторизацию» |
| **BUG_UNKNOWN** | finder → debugger → fixer → reviewer → tester | «крашится при запуске», «баг: не сохраняет» |
| **BUG_KNOWN** | finder → fixer → reviewer → tester | «исправь баг в UserService», «почини логин» |
| **REFACTORING** | finder → analyst → refactorer → reviewer → **integration** → tester | «рефакторинг UserService», «упрости этот код» |
| **PERFORMANCE** | finder → analyst → optimizer → reviewer → tester | «оптимизируй запросы к БД», «тормозит поиск» |
| **INFRASTRUCTURE** | finder → devops → (reviewer → tester) | «настрой CI/CD», «докеризируй проект» |
| **DOCUMENTATION** | finder → documenter | «напиши README», «документируй API» |
| **FEATURE** | finder → analyst → architect → planner → coder → reviewer → **integration** → tester → documenter | «сделай импорт из CSV», «добавь REST API» |

---

## Настройка моделей

Модели всех агентов задаются через конфиг плагина:

**`~/.hermes/plugins/pipeline/config.yaml`**

Три уровня приоритета (высший побеждает):

```
1. agents.<agent_id>     — точечная настройка конкретного агента
2. defaults.<тип>        — групповая настройка по типу провайдера
3. BUILTIN_MODEL_MAP     — хардкод в models.py (см. таблицу выше)
```

Если секция `models` отсутствует или файла нет — используется хардкод.

**Hot-reload:** конфиг перечитывается при каждом вызове инструмента (по mtime с наносекундной точностью). Рестарт не нужен — просто измени config.yaml и следующий вызов подхватит новые настройки.

### Реальный конфиг по умолчанию

```yaml
# ~/.hermes/plugins/pipeline/config.yaml
pipeline:
  models:
    defaults:
      delegate:
        provider: direct            # все Pro → Flash
        model: deepseek-v4-flash
      delegate_free:
        provider: direct            # researcher → Flash
        model: deepseek-v4-flash
    agents:
      security:
        provider: delegate          # только security на Pro
        model: deepseek-v4-pro
```

### Примеры сценариев

**Все Pro перевести во Flash (ноль дорогих вызовов):**

```yaml
pipeline:
  models:
    defaults:
      delegate:
        provider: direct
        model: deepseek-v4-flash
    agents: {}                      # убрать security override
```

**Coder на самую мощную модель:**

```yaml
pipeline:
  models:
    agents:
      coder:
        provider: delegate
        model: openrouter/anthropic/claude-sonnet-4
```

---

## SQLite Kanban (v3.3.0 — @V0rt)

Начиная с v3.3.0, kanban.py работает **напрямую с SQLite**, без CLI.
Все 11 функций (create_parent, create_child, comment, block_task, list_tasks,
show_task, scan_board, promote, complete, claim, assign) пишут/читают kanban.db
через _sqlite_select / _sqlite_update. Это исключает молчаливые ошибки,
которые возвращала _kanban().

Подробный аудит 20 багов: [`ARCHITECTURE-FIXES.md`](ARCHITECTURE-FIXES.md)

---

## Retrospective (v3.2.0)

Плагин пишет структурированный JSONL-лог работы для последующего анализа.

**Где хранится:** `~/.hermes/plugins/pipeline/retro/pipe_<id>.jsonl`

**События (на каждый handler):**
- `pipeline_start` — категория, список агентов
- `agent_start` — агент, модель, размер контекста
- `model_routing` — effective/configured модель
- `convergence` — round, decision, P0/P1/P2 counts, fingerprint
- `findings` — сводка: сколько P0/P1/P2, сколько fixed
- `ensemble_gen/judge` — N, temperatures, winner, mode
- `error` — ошибки с описанием
- `pipeline_clear` — завершение

Конфиг ретроспективы:

```yaml
pipeline:
  retro:
    enabled: true                  # вкл/выкл
    dir: ~/.hermes/plugins/pipeline/retro
    max_files: 100                 # автоочистка
    auto_analyze: false            # выключен — копим данные
```

---

## Конвергенция (v3.2.0)

Оценка сходимости — детерминированная, без LLM.

**Что нового в v3.2.0:**
- ✅ Фильтр `status: fixed` — findings со статусом `fixed`, `accepted`, `none` не считаются
- ✅ Fingerprint только по открытым P0/P1
- ✅ Максимум 3 раунда (P0/P1 → continue → fix → continue → fix → converged/maxed_out)

---

## Best-of-N Ensemble

Для @coder доступен режим генерации N кандидатов с разными температурами и выбор лучшего.

```yaml
pipeline:
  ensemble:
    enabled: true
    agents:
      coder:
        enabled: true
        n: 5
        judge_mode: llm
    cost_optimization:
      disable_on_round_gt: 1
```

---

## Kanban-интеграция

Пайплайн автоматически ведёт доску `pipeline`:

| Событие | Что на доске |
|---------|--------------|
| Старт | Создаётся задача «🔷 Пайплайн: …» с дочерними тасками для каждого агента |
| Агент завершён | Статус `done`, промоутится следующий |
| Конвергенция | Комментарий: «Round N: P0=x, P1=y, P2=z» |
| Converged | Задача → complete |
| Stuck | Задача → blocked |
| Очистка | Задача → complete (Cancelled) |

Статус можно смотреть:

```bash
hermes kanban ls          # все задачи
hermes kanban show <id>   # детали
hermes kanban stats       # статистика доски
```

После рестарта агента (`/new`) — `pipeline_resume()` восстанавливает состояние с доски.

---

## Инструменты плагина (v3.3.0)

| Инструмент | Что делает |
|-----------|------------|
| `pipeline_classify(request)` | Определяет категорию и список агентов |
| `pipeline_save(state)` | Создаёт дерево задач на доске (идемпотентно) |
| `pipeline_load()` | Читает состояние с доски |
| `pipeline_resume()` | Ищет активный пайплайн после рестарта |
| `pipeline_advance(state, agent)` | Отмечает агента завершённым, промоутит следующего |
| `pipeline_clear()` | Закрывает все задачи |
| `pipeline_convergence(state, findings?)` | Оценка сходимости (детерминированная) |
| `pipeline_run_agent(state, agent, context?)` | Delegation package для запуска агента |
| `pipeline_ensemble_run(state, agent, n?)` | Генерация N кандидатов для Best-of-N |
| `pipeline_ensemble_judge(request, candidates)` | Выбор лучшего кандидата |
| `agent_prompt(agent_id, context)` | Собирает промпт для агента из шаблона |
| `agent_model(agent_id)` | Возвращает провайдера и модель для агента |

---

## Обновление

```bash
cd ~/git/hermes-pipeline-plugin
git pull
```

Плагин прилинкован через симлинк — новая версия подхватится автоматически.
После обновления: рестарт сессии (`/new`).

---

## Требования

- **Hermes Agent** — любая версия с поддержкой `register_tool`, `delegate_task` и канального плагина
- **Python** ≥ 3.11
- **PyYAML** — для чтения конфига

---

## Лицензия

MIT
