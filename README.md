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
  ├─ Flash-агенты (finder, coder, tester…) — выполняются прямо в контексте агента
  ├─ Pro-агенты (architect, reviewer, security, integration) — делегируются сабагентам
  └─ Free-агент (researcher) — делегируется через OpenRouter free
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

## Все 17 агентов и их модели

| Агент | Тип | Как выполняется | Дефолтная модель | Что делает |
|-------|-----|----------------|------------------|------------|
| **@finder** | Flash | В контексте | `deepseek-v4-flash` | Разведка: ищет файлы, структуру, зависимости |
| **@analyst** | Flash | В контексте | `deepseek-v4-flash` | Диагностика: что сломалось, где корень |
| **@researcher** | Free | `delegate_task` | `openrouter/free` | Ищет best practices, документацию |
| **@architect** | Pro | `delegate_task` | `deepseek-v4-pro` | Проектирует решение |
| **@planner** | Flash | В контексте | `deepseek-v4-flash` | Декомпозирует на задачи |
| **@coder** | Flash | В контексте | `deepseek-v4-flash` | Пишет код |
| **@editor** | Flash | В контексте | `deepseek-v4-flash` | Редактирует (не во всех пайплайнах) |
| **@fixer** | Flash | В контексте | `deepseek-v4-flash` | Чинит известные баги |
| **@refactorer** | Flash | В контексте | `deepseek-v4-flash` | Рефакторит |
| **@reviewer** | Pro | `delegate_task` | `deepseek-v4-pro` | Код-ревью с качественной оценкой |
| **@security** | Pro | `delegate_task` | `deepseek-v4-pro` | Аудит безопасности |
| **@integration** | Pro | `delegate_task` | `deepseek-v4-pro` | Проверяет кросс-файловую консистентность |
| **@tester** | Flash | В контексте | `deepseek-v4-flash` | Пишет и гоняет тесты |
| **@debugger** | Flash | В контексте | `deepseek-v4-flash` | Отладка (только BUG_UNKNOWN) |
| **@documenter** | Flash | В контексте | `deepseek-v4-flash` | Пишет документацию |
| **@devops** | Flash | В контексте | `deepseek-v4-flash` | Инфраструктура (только INFRASTRUCTURE) |
| **@optimizer** | Flash | В контексте | `deepseek-v4-flash` | Оптимизация (только PERFORMANCE) |

**Три типа выполнения:**
- **Flash** (`direct`) — агент работает прямо в моём контексте. Быстро, дёшево. Подходит для механической работы.
- **Pro** (`delegate`) — я поручаю задачу сабагенту через `delegate_task`. Дороже, но качественнее. Нужно для задач требующих рассуждений и оценки.
- **Free** (`delegate_free`) — то же делегирование, но через бесплатную модель (OpenRouter free). Для второстепенных задач вроде внешних исследований.

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

### Полный пример конфига

```yaml
# ~/.hermes/plugins/pipeline/config.yaml
pipeline:
  models:

    # ── Групповые настройки ──
    # Применяются ко всем агентам соответствующего типа
    defaults:
      direct:                          # Flash-агенты
        model: deepseek-v4-flash
      delegate:                        # Pro-агенты (architect, reviewer, security, integration)
        model: deepseek-v4-pro
      delegate_free:                   # Free-агент (researcher)
        model: openrouter/free

    # ── Точечные настройки ──
    # Переопределяют defaults и BUILTIN для конкретного агента
    agents:
      # Можно переопределить только модель
      coder:
        model: deepseek-v4-pro

      # Можно переопределить провайдер (способ выполнения)
      tester:
        provider: delegate
        model: deepseek-v4-pro

      # Можно переопределить и то, и другое
      architect:
        provider: direct
        model: deepseek-v4-flash

      security:
        model: deepseek-v4-pro
```

### Примеры сценариев

**Экономия — все Pro перевести во Flash (ноль дорогих вызовов):**

```yaml
pipeline:
  models:
    defaults:
      delegate:
        provider: direct
        model: deepseek-v4-flash
```

**Только безопасность на Pro, всё остальное Flash:**

```yaml
pipeline:
  models:
    defaults:
      delegate:
        provider: direct
        model: deepseek-v4-flash
    agents:
      security:
        provider: delegate
        model: deepseek-v4-pro
```

**Coder на Claude Sonnet:**

```yaml
pipeline:
  models:
    agents:
      coder:
        provider: delegate
        model: openrouter/anthropic/claude-sonnet-4
```

**Researcher на другую free-модель:**

```yaml
pipeline:
  models:
    defaults:
      delegate_free:
        model: perplexity/sonar-pro
```

**После изменения конфига** — нужен рестарт сессии (`/new` или `systemctl --user restart hermes-gateway`).

---

## Обновление

```bash
cd ~/git/hermes-pipeline-plugin
git pull
```

Плагин прилинкован через симлинк — новая версия подхватится автоматически.
После обновления: рестарт gateway или сессии.

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

## Инструменты плагина (v2.2)

| Инструмент | Что делает |
|-----------|------------|
| `pipeline_classify(request)` | Определяет категорию и список агентов |
| `pipeline_save(state)` | Создаёт дерево задач на доске |
| `pipeline_load()` | Читает состояние с доски |
| `pipeline_resume()` | Ищет активный пайплайн после рестарта |
| `pipeline_advance(state, agent)` | Отмечает агента завершённым, промоутит следующего |
| `pipeline_clear()` | Закрывает все задачи |
| `pipeline_convergence(state, findings)` | Оценка сходимости (детерминированная, без LLM) |
| `agent_prompt(agent_id, context)` | Собирает промпт для агента из шаблона |
| `agent_model(agent_id)` | Возвращает провайдера и модель для агента |
| `pipeline_run_agent(state, agent_id, context?)` | Возвращает delegation package — инструкцию для запуска агента |

---

## Требования

- **Hermes Agent** — любая версия с поддержкой `register_tool`, `delegate_task` и канального плагина
- **Python** ≥ 3.11
- **Для Pro-агентов** — настроенный провайдер делегации (deepseek-v4-pro или аналог)
- **Для Free-агента** (researcher) — `OPENROUTER_API_KEY` в `.env` (опционально)

---

## Лицензия

MIT
