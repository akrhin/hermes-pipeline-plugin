# 🔱 Hermes Pipeline Plugin

> Multi-agent pipeline orchestrator for Hermes Agent — 8 pipeline categories, quality gates, model routing
> Автоматически разбивает сложные задачи на этапы, запускает специализированных агентов, проверяет качество — и так до 3 раундов, пока не сойдётся.

[![Tests](https://github.com/akrhin/hermes-pipeline-plugin/actions/workflows/test.yml/badge.svg)](https://github.com/akrhin/hermes-pipeline-plugin/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## Как это работает

```
Ты: "добавь JWT аутентификацию в проект"
  │
  ▼
Плагин анализирует → срабатывает триггер SECURITY_RELATED
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

Два компонента: **плагин** (12 инструментов для Hermes Agent) + **скилл** (оркестрация — мои инструкции).

### Быстрая установка

```bash
# 1. Склонировать репозиторий
cd ~
git clone https://github.com/akrhin/hermes-pipeline-plugin.git git/hermes-pipeline-plugin

# 2. Подключить плагин (симлинк)
ln -sf ~/git/hermes-pipeline-plugin ~/.hermes/plugins/pipeline

# 3. Подключить скиллы (симлинки)
ln -sf ~/git/hermes-pipeline-plugin/skill/pipeline-orchestrator \
      ~/.hermes/skills/hermes/pipeline-orchestrator
ln -sf ~/git/hermes-pipeline-plugin/skill/pipeline-ensemble \
      ~/.hermes/skills/pipeline-ensemble
ln -sf ~/git/hermes-pipeline-plugin/skill/pipeline-audit-checklist \
      ~/.hermes/skills/verification/pipeline-audit-checklist

# 4. Включить плагин
hermes plugins enable pipeline

# 5. Создать конфиг (если ещё нет)
cp ~/git/hermes-pipeline-plugin/pipeline.config.yaml.example \
   ~/.hermes/plugins/pipeline/config.yaml
```

**Готово.** Плагин автоматически создаёт `kanban.db` при первом запуске пайплайна. Никаких ручных досок.

### Проверка

```bash
hermes plugins list | grep pipeline   # должен быть enabled
```

### Полный конфиг

```yaml
# ~/.hermes/plugins/pipeline/config.yaml
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

  retro:
    enabled: true
    dir: ~/.hermes/plugins/pipeline/retro
    max_files: 100
    auto_analyze: false
```

### Обновление

```bash
cd ~/git/hermes-pipeline-plugin && git pull
# Плагин прилинкован через симлинк — новая версия подхватится автоматически.
# После обновления: рестарт сессии (/new).
```

---

## Все 16 агентов и их модели

| Агент | Тип | Режим | Модель | Контекст | Что делает |
|-------|-----|-------|--------|----------|------------|
| **@finder** | Flash | `direct` | `deepseek-v4-flash` | research | Разведка: структура, файлы, зависимости |
| **@analyst** | Flash | `direct` | `deepseek-v4-flash` | research | Диагностика: корень проблемы, логические ошибки |
| **@researcher** | Flash | `direct` | `deepseek-v4-flash` | research | Поиск best practices и документации |
| **@architect** | Flash | `direct` | `deepseek-v4-flash` | research, planning | Проектирование решения |
| **@planner** | Flash | `direct` | `deepseek-v4-flash` | planning, infrastructure | Декомпозиция на задачи |
| **@coder** | Flash | `direct` | `deepseek-v4-flash` | implementation, planning | Написание кода с ensemble (5 кандидатов) |
| **@fixer** | Flash | `direct` | `deepseek-v4-flash` | implementation | Исправление известных багов |
| **@refactorer** | Flash | `direct` | `deepseek-v4-flash` | implementation | Рефакторинг без изменения поведения |
| **@reviewer** | Flash | `direct` | `deepseek-v4-flash` | implementation, research | Код-ревью |
| **@security** | **Pro** | **`delegate`** | **`deepseek-v4-pro`** | implementation, research | Аудит безопасности (OWASP Top 10) |
| **@integration** | Flash | `direct` | `deepseek-v4-flash` | implementation, documentation, infrastructure | Кросс-файловая консистентность |
| **@tester** | Flash | `direct` | `deepseek-v4-flash` | implementation | Написание и прогон тестов |
| **@debugger** | Flash | `direct` | `deepseek-v4-flash` | implementation | Отладка (только BUG_UNKNOWN) |
| **@documenter** | Flash | `direct` | `deepseek-v4-flash` | implementation, documentation | Документация |
| **@devops** | Flash | `direct` | `deepseek-v4-flash` | infrastructure | Инфраструктура (только INFRASTRUCTURE) |
| **@optimizer** | Flash | `direct` | `deepseek-v4-flash` | implementation | Оптимизация (только PERFORMANCE) |

**Два режима выполнения:**
- **Flash** (`direct`) — агент работает прямо в моём контексте. Быстро, дёшево. Подходит для механической работы.
- **Pro** (`delegate`) — я поручу задачу сабагенту через `delegate_task`. Дороже, но качественнее. Используется только для security-аудита.

> **Примечание:** по умолчанию все агенты — Flash. Security переведён на Pro через конфиг.
> Файлы `.prompt` есть для всех 16 агентов. Без файла — генерируется default prompt из AGENT_CONTEXT_FIELDS.

---

## Интеграция с code-review-graph (v3.6.0)

[**code-review-graph**](https://github.com/tirth8205/code-review-graph) (22.7k ★) — локальный граф кода на Tree-sitter + SQLite. Строит карту зависимостей, вычисляет blast radius изменений, риск-скоринг и test gaps.

### Для чего

Агенты **@reviewer** и **@security** теперь используют CRG вместо сканирования всего репозитория. Граф даёт им точный набор файлов и функций для проверки — экономия токенов **38–528×** на больших кодовых базах.

### Как установить

```bash
# Установить CRG (через uv/pipx)
pip install code-review-graph
# или
uv tool install code-review-graph

# Собрать граф для проекта
cd ~/git/your-project
code-review-graph build

# Включить как MCP-сервер Hermes
# → прописать в ~/.hermes/config.addon.yaml:
#   code-review-graph:
#     command: /home/sintez/.local/bin/code-review-graph
#     args: [mcp, --repo, /home/sintez/git/your-project, --auto-watch]
#     enabled: true
```

После рестарта Hermes (`/new`) инструменты CRG появляются как `mcp_code_review_graph_*` и автоматически используются агентами @reviewer и @security.

### MCP-инструменты CRG, доступные в пайплайне

| Инструмент | Что даёт |
|-----------|----------|
| `get_review_context_tool` | Полный контекст для ревью: blast radius, risk score, affected flows, test gaps |
| `get_impact_radius_tool` | Детальный разбор затронутых функций по графу |
| `query_graph_tool` | Точечный запрос: callers_of, callees_of, tests_for, file_summary |
| `list_graph_stats_tool` | Статистика графа (узлы, рёбра, файлы, языки) |
| `build_or_update_graph_tool` | Пересборка графа (полная или инкрементальная) |

### Конфигурация

Граф собирается один раз и обновляется автоматически (`--auto-watch`). Для смены проекта — измени `--repo` в MCP-конфиге и сделай `/new`.

---

## Retro logging (v3.5.1)
Начиная с v3.5.1, **ретро-логирование фиксирует полные метаданные**: agent_done пишет duration_s/tokens_response/status, tokens_prompt считается от реального промпта, pipeline_resume логирует категорию/round/агентов.

Начиная с v3.3.0, **kanban.py работает напрямую с SQLite, без CLI-прослойки**. Это собственный kanban плагина, не путать с `hermes kanban`.

Все 11 функций Kanban API:
- `create_parent()`, `create_child()` — прямой INSERT
- `comment()` — прямой INSERT
- `block_task()` — прямой UPDATE
- `list_tasks()` — прямой SELECT
- `show_task()` — SELECT с JOIN
- `scan_board()` — прямой SELECT (ядро load/resume/clear)
- `promote()`, `complete()` — напрямую в SQLite

**Что это даёт:**
- ✅ Нет молчаливых ошибок от `_kanban()` (которая возвращала `{}` при любом сбое)
- ✅ Нет зависимости от `hermes kanban` CLI (ломающегося при изменении формата)
- ✅ Работает без daemon (не требует `kanban watch`)
- ✅ Быстрее: SQLite вместо subprocess для каждого вызова

Подробный аудит: [`ARCHITECTURE-FIXES.md`](ARCHITECTURE-FIXES.md) — 20 багов (4 P0 + 7 P1 + 9 P2)

---

## Категории пайплайнов

| Категория | Пайплайн | Примеры запросов |
|-----------|----------|-----------------|
| **SECURITY_RELATED** | finder → analyst → researcher → architect → planner → coder → reviewer → **security** → **integration** → tester → documenter | «добавь JWT», «проверь на уязвимости» |
| **BUG_UNKNOWN** | finder → debugger → fixer → reviewer → tester | «крашится при запуске», «баг: не сохраняет» |
| **BUG_KNOWN** | finder → fixer → reviewer → tester | «исправь баг в UserService» |
| **REFACTORING** | finder → analyst → refactorer → reviewer → **integration** → tester | «рефакторинг UserService» |
| **PERFORMANCE** | finder → analyst → optimizer → reviewer → tester | «оптимизируй запросы к БД» |
| **INFRASTRUCTURE** | finder → devops → (reviewer → tester) | «настрой CI/CD», «докеризируй проект» |
| **DOCUMENTATION** | finder → documenter | «напиши README», «документируй API» |
| **FEATURE** | finder → analyst → architect → planner → coder → reviewer → **integration** → tester → documenter | «сделай импорт из CSV» |

---

## Настройка моделей

Модели всех агентов задаются через конфиг плагина:

**`~/.hermes/plugins/pipeline/config.yaml`**

Три уровня приоритета (высший побеждает):
```
1. agents.<agent_id>     — точечная настройка конкретного агента
2. defaults.<тип>        — групповая настройка по типу провайдера
3. BUILTIN_MODEL_MAP     — хардкод в models.py
```

**Hot-reload:** конфиг перечитывается при каждом вызове инструмента (по mtime с наносекундной точностью). Рестарт не нужен.

---

## Retrospective — логирование прогонов

Плагин пишет структурированный JSONL-лог каждого прогона пайплайна в директорию `~/.hermes/plugins/pipeline/retro/`.

### Для чего это нужно

- **Диагностика** — если агент повёл себя неожиданно, ретро-лог покажет что именно произошло
- **Анализ сходимости** — как convergence принимал решения, какие были findings
- **Детерминизм ensemble** — какие температуры генерировались, какой кандидат победил
- **Performance** — сколько времени занял каждый агент, какой round
- **Саморефлексия** — плагин может анализировать собственные логи

### Какие события логируются

| Событие | Описание |
|---------|----------|
| `pipeline_start` | Категория, список агентов |
| `model_routing` | Какая модель назначена агенту |
| `agent_start` | Запуск агента, модель, directive |
| `agent_done` | Завершение агента |
| `ensemble_gen` | Генерация N кандидатов, температуры |
| `ensemble_judge` | Выбор победителя, mode |
| `convergence` | Решение: converged/continue/stuck/maxed_out |
| `findings` | Сводка: P0/P1/P2/fixed |
| `findings_detail` | Детали каждого finding |
| `error` | Ошибки с traceback |
| `pipeline_clear` | Завершение пайплайна |

### Как смотреть

```bash
# Все лог-файлы
ls ~/.hermes/plugins/pipeline/retro/

# Содержимое конкретного прогона
cat ~/.hermes/plugins/pipeline/retro/pipe_t_<id>.jsonl

# Сводка: сколько событий каждого типа
cat ~/.hermes/plugins/pipeline/retro/*.jsonl | python3 -c "
import sys,json
cats={}
for l in sys.stdin:
    e=json.loads(l)
    cats[e['event']]=cats.get(e['event'],0)+1
for k,v in sorted(cats.items()):
    print(f'{k}: {v}')
"
```

---

## Конвергенция

Оценка сходимости — детерминированная, без LLM.

- ✅ Фильтр `status: fixed` — findings со статусом `fixed`, `accepted`, `none` не считаются
- ✅ Fingerprint только по открытым P0/P1
- ✅ Максимум 3 раунда
- ✅ `reopen()` — переоткрытие done-задач для convergence-циклов (v3.3.0)

---

## Best-of-N Ensemble

Для @coder доступен режим генерации N кандидатов с разными температурами и выбор лучшего через LLM Judge.

- **5 кандидатов** (T=0.3, 0.5, 0.7, 0.9, 1.1)
- **LLM Judge** реально оценивает кандидатов через `delegate_task` (багфикс #3 v3.3.3)
- На round ≥ 2 ensemble автоматически отключается (экономия токенов)

---

## Инструменты плагина (v3.3.3 — 12 штук)

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
| `pipeline_ensemble_judge(request, candidates)` | Выбор лучшего кандидата (LLM Judge) |
| `agent_prompt(agent_id, context)` | Собирает промпт для агента из шаблона |
| `agent_model(agent_id)` | Возвращает провайдера и модель для агента |

---

## Требования

- **Hermes Agent** — любая версия с поддержкой плагинов
- **Python** ≥ 3.11
- **sqlite3** — встроенный модуль Python
- **PyYAML** — для чтения конфига

---

## Контрибуторы

См. [`CONTRIBUTORS.md`](CONTRIBUTORS.md)

## Changelog

См. [`CHANGELOG.md`](CHANGELOG.md)

## Лицензия

MIT
