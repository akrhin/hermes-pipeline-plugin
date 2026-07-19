# Ensemble / Best-of-N — Архитектура и план реализации

**Pipeline Plugin v3.0 (proposed)**

---

## 1. Анализ: какие агенты выиграют от ensemble

### Self-Consistency vs Best-of-N

| Метод | Описание | N генераций | Выбор финального |
|-------|----------|-------------|------------------|
| **Self-Consistency** | N независимых reasoning paths → majority vote | N | Majority vote |
| **Best-of-N** | N полных решений → judge выбирает лучшее | N | Оценка judge |

**Вывод:** для pipeline plugin релевантен **Best-of-N** — агенты генерируют готовые артефакты (код, план), а не цепочки рассуждений.

### Матрица применимости по агентам

| Агент | Тип | N=5 benefit | Cost multiplier | Вердикт |
|-------|-----|-------------|-----------------|---------|
| **@coder** | Flash (direct) | **Высокий** — код имеет высокую variance, N=5 даёт ~80% выгоды от N=40 | ~5× (дешево: Flash) | **✅ Первичная цель** |
| **@planner** | Flash (direct) | Средний — планы могут различаться по качеству | ~5× (дешево: Flash) | **✅ Вторичная цель** |
| **@architect** | Pro (delegate) | Средний — но архитектура дорогая, диверсификация полезна | ~5× (дорого: Pro) | **⚠️ Опционально** (конфиг) |
| **@tester** | Flash (direct) | Средний — тесты могут покрывать разные кейсы | ~5× (дешево: Flash) | **✅ Вторичная цель** |
| **@reviewer** | Pro (delegate) | Низкий — ревью больше про качество, не diversity | — | **❌ Нецелесообразно** |
| **@security** | Pro (delegate) | Низкий — security лучше depth, не breadth | — | **❌** |
| **@finder/@analyst** | Flash | Низкий — поиск/анализ детерминированы | — | **❌** |
| **@documenter** | Flash | Низкий | — | **❌** |
| **@integration** | Pro | Низкий — проверки детерминированы | — | **❌** |
| **@fixer/@refactorer** | Flash | Средний — фиксы могут быть разными | ~5× | **⚠️ Конфиг** |

### Sweet spot: N

- **N=5** — 80% выгоды от N=40 (эмпирическое правило Wang et al. 2022)
- **N=3** — минимальный ensemble (простое большинство)
- **N=10** — для production-grade кода
- Стоимость: 5 × 0.12 руб (Flash) = **0.60 руб** за одну генерацию coder-ensemble

**Вывод:** @coder с N=5 — первичная и наиболее выгодная цель.

---

## 2. Архитектура @coder-ensemble

### 2.1. Высокоуровневая схема

```
Пайплайн до @coder:
  @finder → @analyst → @architect → @planner
                              │
                              ▼  context (реализация)
                     ┌─── @coder-ensemble ────┐
                     │                        │
                     │  ┌─ кандидат 1 ──┐     │
                     │  │ prompt + ctx  │     │
                     │  └──────┬───────-┘     │
                     │         │ delegate     │
                     │  ┌─ кандидат 2 ──┐     │
                     │  │ prompt + ctx  │     │ delegate_parallel
                     │  └──────┬───────-┘     │ (max 6)
                     │  ┌─ кандидат 3 ──┐     │
                     │  │ prompt + ctx  │     │
                     │  └──────┬───────-┘     │
                     │  ┌─ кандидат 4 ──┐     │
                     │  │ prompt + ctx  │     │
                     │  └──────┬───────-┘     │
                     │  ┌─ кандидат 5 ──┐     │
                     │  │ prompt + ctx  │     │
                     │  └──────┬───────-┘     │
                     │         │              │
                     │    ┌────┴─────┐        │
                     │    │  @judge   │        │
                     │    │ выбирает  │        │
                     │    │ лучший    │        │
                     │    └────┬─────┘        │
                     │         │              │
                     │    победитель          │
                     └─────────┬──────────────┘
                               │
                               ▼
  @reviewer → @integration → @tester → @documenter
```

### 2.2. Компоненты

#### Component A: `ensemble.py` — ядро ensemble-логики

```python
# ensemble.py — новый модуль
#
# Основные функции:
#   generate_candidates(state, agent_id, n) → list[call_args]
#     Готовит N пакетов для delegate_parallel:
#       - Одна и та же задача, но с вариацией prompt
#       - Вариация: temperature {0.3, 0.5, 0.7, 0.9, 1.1}
#       - Или: рандомизированный порядок секций контекста
#       - Или: разные seed / инструкции "подойди иначе"
#
#   judge(candidates_results, context) → winner
#     Принимает N результатов + контекст задачи.
#     Возвращает победителя {id, result, rationale}.
#
#   format_ensemble_result(winner, all_results) → {code, rationale, candidates_meta}
#     Форматирует финальный результат для передачи дальше.

CANDIDATE_VARIATIONS = [
    {"temperature": 0.3, "instruction_extra": "Будь консервативен. Пиши минимальные изменения."},
    {"temperature": 0.5, "instruction_extra": "Пиши clean code с комментариями."},
    {"temperature": 0.7, "instruction_extra": "Оптимизируй производительность."},
    {"temperature": 0.9, "instruction_extra": "Сфокусируйся на читаемости и тестах."},
    {"temperature": 1.1, "instruction_extra": "Сделай production-grade решение."},
]
```

#### Component B: Judge-агент

**Два режима для judge:**

| Режим | Как работает | Когда использовать |
|-------|-------------|-------------------|
| **LLM Judge** | `delegate_task` с prompt: "Выбери лучшее из N решений по критериям: correctness, completeness, code quality, security" | Production (качественнее) |
| **Deterministic Judge** | Эвристики: длина кода, наличие тестов, стиль, покрытие | MVP / экономия |

**LLM Judge prompt (шаблон):**

```
Ты — judge в системе Best-of-N code generation.
Задача: "{request}"
Контекст: {context}

Вот N решений от разных генераций:

{candidates_table}

Оцени каждое по 4 критериям (0-10):
1. Correctness — решает ли задачу
2. Completeness — всё ли реализовано
3. Code Quality — стиль, чистота, best practices
4. Security — нет ли очевидных уязвимостей

Формат ответа (строго JSON):
{
  "winner_id": "candidate_3",
  "scores": [{"id": "candidate_1", "total": 35, ...}, ...],
  "rationale": "Candidate 3 выбран потому что...",
  "improvements": ["Добавить error handling", ...]
}
```

#### Component C: Генерация вариаций

Вариации prompt для diversity без изменения смысла:

```python
# 5 стратегий вариации (для N=5)
VARIATION_STRATEGIES = [
    {
        "name": "conservative",
        "temperature": 0.3,
        "system_extra": "Минимальные изменения. Без рефакторинга."
    },
    {
        "name": "clean",
        "temperature": 0.5,
        "system_extra": "Чистый код с комментариями и type hints."
    },
    {
        "name": "balanced",
        "temperature": 0.7,
        "system_extra": "Стандартный production код."
    },
    {
        "name": "thorough",
        "temperature": 0.9,
        "system_extra": "Полное решение с тестами, обработкой ошибок, логами."
    },
    {
        "name": "creative",
        "temperature": 1.1,
        "system_extra": "Нестандартный подход. Оптимизация, инновации."
    },
]
```

### 2.3. Интеграция с Kanban

**Без ensemble (текущее):**
```
Parent: 🔷 Пайплайн: "добавить JWT"
  ├── @finder: ...     [done]
  ├── @analyst: ...    [done]
  ├── @architect: ...  [done]
  ├── @planner: ...    [done]
  ├── @coder: ...      [ready → running → done]
  ├── @reviewer: ...   [todo]
  └── ...
```

**С ensemble (предлагаемое):**
```
Parent: 🔷 Пайплайн: "добавить JWT"  [ensemble: coder@5]
  ├── @finder: ...            [done]
  ├── @analyst: ...           [done]
  ├── @architect: ...         [done]
  ├── @planner: ...           [done]
  ├── @coder (ensemble)       [running]
  │   ├── @coder/candidate-1  [done]
  │   ├── @coder/candidate-2  [running]
  │   ├── @coder/candidate-3  [running]
  │   ├── @coder/candidate-4  [todo]
  │   ├── @coder/candidate-5  [todo]
  │   └── @judge              [todo → after all candidates done]
  ├── @reviewer: ...          [todo]
  └── ...
```

**Принцип:** ensemble — это не отдельный агент, а **режим** работы агента. В kanban это отображается как веер подтасков под @coder.

### 2.4. Интеграция с Convergence Engine

Convergence engine НЕ меняется для ensemble. Он работает на уровне findings после всех агентов. Ensemble влияет только на качество входа @coder, не на логику конвергенции.

```
# Current:
1. coder → 2. reviewer → 3. ... → N. convergence
   ↑ findings ← convergence может вызвать coder снова

# С ensemble:
1. coder-ensemble → 2. reviewer → 3. ... → N. convergence
   ↑ findings ← convergence может вызвать coder-ensemble снова
```

**Дополнение:** на convergence-раундах (round 2+) ensemble может быть отключён — достаточно одного кандидата от @coder для фиксов.

### 2.5. Поток данных через state

```python
# Поля state, добавляемые для ensemble:
{
    "ensemble": {
        "enabled_agents": ["coder"],     # какие агенты в ensemble
        "n": 5,                          # количество кандидатов
        "judge_model": "deepseek-v4-flash",  # модель для judge
        "results": {
            "coder": {
                "n": 5,
                "winner": {"id": "candidate_3", ...},
                "candidates": [
                    {"id": "candidate_1", "result": "...", "meta": {"temperature": 0.3, ...}},
                    ...
                ],
                "judge_rationale": "Candidate 3 выбран потому что..."
            }
        }
    },
    # существующие поля state остаются без изменений
}
```

---

## 3. План реализации

### Фаза 0: Proof of Concept (1-2 дня)

**Цель:** Проверить, что ensemble даёт измеримое улучшение кода на реальных задачах.

**Что делаем:**
1. Ручное тестирование: запустить 5 генераций @coder на 3-х задачах
2. LLM Judge сравнивает результаты
3. Метрика: win rate лучшего кандидата vs single

**Артефакт:** `ensemble_poc_results.md` с результатами.

**Код:** Ничего не меняем в плагине — только скрипты.
**Файлы:** `experiments/poc_ensemble.py` (внешний скрипт)

### Фаза 1: MVP (3-5 дней)

**Цель:** Работающий @coder-ensemble в пайплайне.

#### Файлы для создания:

| Файл | Назначение |
|------|-----------|
| `ensemble.py` | Ядро: generate_candidates, judge (deterministic/LLM), format_ensemble_result |
| `agents/judge.prompt` | Prompt-шаблон для LLM Judge |
| `tests/test_ensemble.py` | Unit-тесты ensemble-логики |

#### Файлы для изменения:

| Файл | Изменение |
|------|----------|
| `__init__.py` | + новый инструмент `pipeline_ensemble_run` |
| `__init__.py` | + `ENSEMBLE_SCHEMA` |
| `__init__.py` | + регистрация инструмента и хендлера |
| `kanban.py` | + создание N подтасков для ensemble |
| `kanban.py` | + `advance_ensemble()` — manage sub-tasks lifecycle |
| `models.py` | + ensemble config (N, judge_model, enabled_agents) |
| `plugin.yaml` | v3.0.0 — 11 tools (+pipeline_ensemble_run) |

#### schema для нового инструмента:

```python
ENSEMBLE_SCHEMA = {
    "name": "pipeline_ensemble_run",
    "description": (
        "Run a pipeline agent in Best-of-N ensemble mode. "
        "Generates N independent candidates via delegate_parallel, "
        "then a judge selects the best one. "
        "Returns the winner + all candidates metadata."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "state": {
                "type": "object",
                "description": "Current pipeline state",
            },
            "agent_id": {
                "type": "string",
                "description": "Agent to run in ensemble mode (e.g. 'coder')",
            },
            "n": {
                "type": "integer",
                "description": "Number of candidates (default: 5, max: 10)",
                "default": 5,
                "minimum": 2,
                "maximum": 10,
            },
            "judge_mode": {
                "type": "string",
                "enum": ["llm", "deterministic"],
                "description": "Judge mode: llm (delegate to judge agent) or deterministic (heuristics)",
                "default": "llm",
            },
        },
        "required": ["state", "agent_id"],
    },
}
```

#### Config extension (models.py):

```yaml
pipeline:
  models:
    # ... existing model config ...

  ensemble:
    enabled: true
    default_n: 5
    max_n: 10
    agents:
      coder:
        enabled: true
        n: 5
        judge_mode: llm
        temperature_range: [0.3, 1.1]  # для вариаций
      planner:
        enabled: false
        n: 3
        judge_mode: deterministic
    judge:
      model: deepseek-v4-flash
      # или делегировать Pro:
      # model: deepseek-v4-pro
      # provider: delegate
    cost_optimization:
      # Отключать ensemble на convergence rounds (2+)
      disable_on_round_gt: 1
      # Минимальная сложность задачи (по длине контекста)
      min_task_complexity: 500  # chars
```

### Фаза 2: Production (5-7 дней)

**Цель:** Полноценный ensemble для @coder + @planner + @tester с конфигурацией и мониторингом.

#### Дополнительные изменения:

| Файл | Изменение |
|------|----------|
| `ensemble.py` | + planner-ensemble вариации |
| `ensemble.py` | + tester-ensemble вариации |
| `ensemble.py` | + cost_optimization: auto-disable ensemble при convergence rounds |
| `ensemble.py` | + selective ensemble: только для сложных задач (heuristic) |
| `kanban.py` | + parallel sub-task visualization |
| `classify.py` | + ensemble-aware pipeline (опционально) |
| `tests/test_ensemble.py` | + тесты для planner/tester ensemble |
| `tests/test_ensemble_integration.py` | + интеграционные тесты |
| `AGENTS.md` | + секция про ensemble |
| `ARCHITECTURE.md` | + обновление |
| `ENSEMBLE-ARCHITECTURE.md` | + post-mortem / lessons learned |

### Фаза 3: Оптимизация (непрерывно)

**Цель:** Снижение cost-per-quality, адаптивный N.

- **Adaptive N:** начинать с N=5, на следующих раундах N=3 (меньше багов — меньше diversity нужно)
- **Caching:** если тот же запрос — reuse предыдущего winner
- **Speculative execution:** запускать judge параллельно с последним кандидатом
- **A/B тестинг:** ensemble vs single — сравнивать reviewer findings ratio
- **Cost dashboard:** `pipeline_ensemble_stats` — показывать cost savings

---

## 4. Архитектурная диаграмма (текстовая)

```
┌─────────────────────────────────────────────────────────────────────────┐
│                      Pipeline Plugin v3.0                              │
│                    + Ensemble / Best-of-N                               │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  USER REQUEST                                                          │
│  "добавить JWT аутентификацию"                                         │
└─────────────────────────────┬───────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  1. classify(request) → category: FEATURE, pipeline: [finder..coder]  │
│  2. save → create task tree on board                                   │
│  3. Run agents sequentially...                                         │
│     @finder → @analyst → @architect → @planner                         │
└─────────────────────────────┬───────────────────────────────────────────┘
                              │
                              ▼
┌────────────────── @coder-ensemble (NEW) ─────────────────────────────┐
│                                                                       │
│  ┌── pipeline_ensemble_run(state, "coder", n=5) ──────────────────┐ │
│  │                                                                  │ │
│  │  Step 1: PREPARE                                                │ │
│  │  ┌──────────────────────────────────────────┐                  │ │
│  │  │ generate_candidates(state, "coder", 5)    │                  │ │
│  │  │ → 5x call_args с вариациями prompt        │                  │ │
│  │  │ → вариации: temperature + instruction_extra │                  │ │
│  │  └──────────────────────┬───────────────────┘                  │ │
│  │                         │                                       │ │
│  │  Step 2: GENERATE (parallel)                                    │ │
│  │  ┌──────────────────────┴───────────────────┐                  │ │
│  │  │ delegate_parallel(tasks=[cand1..cand5])   │                  │ │
│  │  │                                          │                  │ │
│  │  │  ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐           │ │
│  │  │  │cand 1│ │cand 2│ │cand 3│ │cand 4│ │cand 5│           │ │
│  │  │  │T=0.3 │ │T=0.5 │ │T=0.7 │ │T=0.9 │ │T=1.1 │           │ │
│  │  │  └──┬───┘ └──┬───┘ └──┬───┘ └──┬───┘ └──┬───┘           │ │
│  │  │     └────────┴────────┴────────┴────────┘                │ │
│  │  │                все 5 результатов                          │ │
│  │  └──────────────────────┬───────────────────┘                  │ │
│  │                         │                                       │ │
│  │  Step 3: JUDGE                                                 │ │
│  │  ┌──────────────────────┴───────────────────┐                  │ │
│  │  │ LLM Judge оценивает 5 кандидатов          │                  │ │
│  │  │ по 4 критериям:                           │                  │ │
│  │  │  - Correctness   (0-10)                  │                  │ │
│  │  │  - Completeness  (0-10)                  │                  │ │
│  │  │  - Code Quality  (0-10)                  │                  │ │
│  │  │  - Security      (0-10)                  │                  │ │
│  │  │ → winner + rationale + improvements      │                  │ │
│  │  └──────────────────────┬───────────────────┘                  │ │
│  │                         │                                       │ │
│  │  Step 4: FORMAT RESULT                                         │ │
│  │  ┌──────────────────────┴───────────────────┐                  │ │
│  │  │ format_ensemble_result(winner, candidates) │                  │ │
│  │  │ → {code, rationale, candidates_meta}      │                  │ │
│  │  └──────────────────────────────────────────┘                  │ │
│  └─────────────────────────────────────────────────────────────────┘ │
│                                                                       │
│  Результат пишется в state.ensemble.results.coder                    │
└─────────────────────────────┬─────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  @reviewer → @integration → @tester → @documenter                     │
│                                                                       │
│  Convergence:                                                 │
│  ┌─────────────────────────────────────────────────────────────────┐ │
│  │ pipeline_convergence(state, findings)                          │ │
│  │ → converged?  ✅ готово, pipeline_clear()                     │ │
│  │ → continue?   🔄 следующий раунд (coder без ensemble —         │ │
│  │                 cost optimization: disable_on_round_gt > 1)    │ │
│  │ → stuck/maxed? ❌ эскалация                                    │ │
│  └─────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 5. Варианты prompt-вариаций для @coder

### Стратегия 1: Temperature sweep

| Candidate | Temperature | Instruction extra |
|-----------|-------------|-------------------|
| 1 | 0.3 | Минимальные изменения, консервативно |
| 2 | 0.5 | Чистый код с комментариями |
| 3 | 0.7 | Стандартный подход |
| 4 | 0.9 | Полное решение с тестами |
| 5 | 1.1 | Нестандартный подход, креативно |

### Стратегия 2: Style/priority sweep

| Candidate | Фокус | Instruction extra |
|-----------|-------|-------------------|
| 1 | Correctness | Только корректность, без оптимизаций |
| 2 | Readability | Читаемость > производительность |
| 3 | Performance | Оптимизация > читаемость |
| 4 | Completeness | Все edge cases, exhaustive |
| 5 | Simplicity | Минимум кода, KISS |

### Стратегия 3: Context subsampling

Разные кандидаты получают разный объём контекста:
- Candidate 1: полный контекст
- Candidate 2: только implementation_context
- Candidate 3: implementation + quality
- Candidate 4: implementation + planning
- Candidate 5: полный контекст + reversed order

---

## 6. Экономика

### Стоимость одной генерации @coder

| Компонент | Модель | Cost |
|-----------|--------|------|
| 1× @coder (single) | deepseek-v4-flash | ~0.12 руб |
| 5× @coder (ensemble) | deepseek-v4-flash | ~0.60 руб |
| 1× LLM Judge | deepseek-v4-flash | ~0.06 руб |
| **Total ensemble** | | **~0.66 руб** |
| **Overhead vs single** | | **~5.5×** |

### Cost-benefit

- **Без ensemble:** 0.12 руб/запуск, но риск итераций конвергенции
- **С ensemble:** 0.66 руб/запуск, но меньше convergence rounds (качество выше с первого раза)
- **Точка безубыточности:** если ensemble сокращает >1 convergence round — выгодно

```
Без ensemble:
  1 запуск @coder (0.12) + convergence round 2 (0.12) = 0.24 руб
  + convergence round 3 (0.12) = 0.36 руб (max_rounds=3)

С ensemble:
  1 запуск @coder-ensemble (0.66) + 0 convergence rounds = 0.66 руб
```

Если ensemble снижает convergence rounds с 2.5 до 1.0 в среднем — cost-neutral.

---

## 7. Риски и митигации

| Риск | Вероятность | Митигация |
|------|-------------|-----------|
| Кандидаты слишком похожи (low diversity) | Средняя | Temperature sweep + random seed + instruction_extra |
| Judge выбирает не лучшего | Высокая | Deterministic judge fallback, review judge output |
| N=5 всё ещё дорого | Средняя | Cost optimization: отключать на convergence rounds, adaptive N |
| Complexity: orchestrator запутан | Средняя | Чёткое разделение: ensemble.py — только логика, orchestrator — только вызовы |
| Kanban sub-tasks засоряют доску | Низкая | Опционально: не создавать подтаски, только parent @coder с метаданными |

---

## 8. Критерии готовности (Definition of Done)

### MVP (Фаза 1)

- [ ] `ensemble.py` реализует `generate_candidates` и `judge` (deterministic)
- [ ] `pipeline_ensemble_run` зарегистрирован как 11-й инструмент
- [ ] @coder-ensemble работает в FEATURE pipeline
- [ ] Kanban отображает ensemble sub-tasks
- [ ] Config `pipeline.ensemble` читается из models.py
- [ ] Unit-тесты для ensemble.py (без Kanban CLI)
- [ ] Все существующие тесты проходят

### Production (Фаза 2)

- [ ] LLM Judge работает с judge.prompt
- [ ] @planner-ensemble, @tester-ensemble
- [ ] Cost optimization: auto-disable на convergence rounds
- [ ] Конфиг с per-agent настройками
- [ ] Интеграционные тесты (с Kanban CLI mock)
- [ ] Документация обновлена (AGENTS.md, ARCHITECTURE.md)

---

## 9. Roadmap

```
Фаза 0: PoC                   ─── 1-2 дня  ───  Эксперименты, метрики
    ↓
Фаза 1: MVP @coder-ensemble   ─── 3-5 дней ───  ensemble.py + pipeline_ensemble_run
    ↓
Фаза 2: Production            ─── 5-7 дней ───  planner/tester, LLM Judge, config
    ↓
Фаза 3: Optimization          ─── ongoing  ───  adaptive N, caching, cost dashboard
```

---

## 10. Сводка файлов для создания/изменения

### Создать:

| # | Файл | Описание |
|---|------|----------|
| 1 | `ensemble.py` | Ядро: generate_candidates, judge, format_ensemble_result |
| 2 | `agents/judge.prompt` | Prompt-шаблон для LLM Judge |
| 3 | `tests/test_ensemble.py` | Unit-тесты |
| 4 | `ENSEMBLE-ARCHITECTURE.md` | Этот документ |

### Изменить:

| # | Файл | Что |
|---|------|-----|
| 5 | `__init__.py` | + `pipeline_ensemble_run` инструмент (11-й) |
| 6 | `models.py` | + ensemble config секция |
| 7 | `kanban.py` | + ensemble sub-tasks creation |
| 8 | `plugin.yaml` | v3.0.0 |

### Опционально (Фаза 2):

| # | Файл | Что |
|---|------|-----|
| 9 | `classify.py` | + ensemble-aware pipeline variant |
| 10 | `tests/test_ensemble_integration.py` | Интеграционные тесты |
| 11 | `AGENTS.md` | + ensemble секция |
| 12 | `ARCHITECTURE.md` | + ensemble update |
