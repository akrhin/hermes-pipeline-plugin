# Архитектура исправлений Pipeline Plugin (2026-07-20)

На основе code review (20 багов) — спроектировано для akrhin/hermes-pipeline-plugin.

## Содержание

1. [Карта багов → root cause](#1-карта-багов--root-cause)
2. [Приоритет фиксов (P0→P1→P2)](#2-приоритет-фиксов)
3. [Набор минимальных PR-изменений](#3-набор-минимальных-pr-изменений)
4. [Архитектура convergence/reopen cycle](#4-архитектура-convergencereopen-cycle)
5. [Что фиксить у себя (локально) vs отправить автору](#5-разделение-ответственности)

---

## 1. Карта багов → root cause

### P0 (4)

| # | Баг | Файл | Строки | Root cause |
|---|-----|------|--------|------------|
| 1 | `convergence('continue')` не перезапускает coder | `kanban.py` | 564–571, 166–169 | `unblock()` → `promote()` апдейтит только `todo/blocked` → `ready`. Coder в `done` — не находит. Нет функции `reopen()`. |
| 2 | `HERMES_HOME` игнорируется | `kanban.py:73`, `models.py:46`, `ensemble.py:51` | 73–76 | Три функции читают `HERMES_HOME` правильно, но приложение запускается под другим пользователем (systemd) где `$HERMES_HOME` не экспортирован. Проблема не в коде, а в окружении. Нужен fallback к config.yaml Hermes. |
| 3 | LLM Judge возвращает фальшивый winner_id | `ensemble.py` | 160–171 | `judge_candidates(mode="llm")` строит промпт, но **не вызывает LLM**. Возвращает `candidates[len(candidates)//2]["id"]` с заглушкой "LLM Judge would evaluate here". |
| 4 | Flash-агенты не получают prompt | `__init__.py` | 543–554 | `handle_run_agent()` для `directive="direct"` делает return early с `prompt: None`. Промпт для Flash не строится никогда. |

### P1 (7)

| # | Баг | Файл | Строки | Root cause |
|---|-----|------|--------|------------|
| 5 | 8/12 handler'ов теряют stack trace | `__init__.py` | 358,369,380,391,402,504,627,646 | `except Exception as e: return json.dumps({"error": str(e)})` — без `traceback.format_exc()`. |
| 6 | `scan_board()` не восстанавливает context/findings | `kanban.py` | 700–713 | Ставит `round: 0, findings: []` всегда. Не парсит комментарии родительской таски. |
| 7 | metadata в `complete()` игнорируется | `kanban.py` | 181–201 | Параметр `metadata` принимается, но никуда не сохраняется. |
| 8 | `handle_convergence` мутирует state по ссылке | `__init__.py:328`, `kanban.py:420` | 420–435 | `evaluate_convergence()` добавляет `findings`, `findings_fingerprint`, `round` прямо в переданный dict. Оркестратор теряет исходное состояние. |
| 9 | 'док' в classify даёт false positive | `classify.py` | 89 | `"док"` в DOCUMENTATION ловит `docker`, `доклады`. Word-boundary regex (`\bдок\b`) не спасает в кириллице. |
| 10 | integration.prompt: мёртвый 'Full context' | `agents/integration.prompt` | 10–11 | Строка `### Full context` без переменной. `AGENT_CONTEXT_FIELDS` не включает `full_context` для integration. |
| 11 | maxed_out не закрывает детей | `kanban.py` | 554–562 | Ветка `decision == "maxed_out"` делает `complete(parent_id)` но не итерирует детей (в отличие от `converged`). |

### P2 (9)

| # | Баг | Файл | Строки | Root cause |
|---|-----|------|--------|------------|
| 12 | `_sqlite_update` лишний import os | `kanban.py` | 21 | `import os` используется в `_db_path()` — не лишний. False positive. |
| 13 | Пустой findings → ложная convergence | `kanban.py` | 426–455 | Если `findings=[]`, `p0p1` пуст → `converged` сразу, даже без единого раунда анализа. |
| 14 | blocked не найден scan_board | `kanban.py` | 641–647, 697 | Родитель ищется по `IN ('running','ready','todo','blocked')` — `blocked` включён. Но дочерняя логика (строка 697) не обрабатывает `blocked` для определения current_idx. |
| 15 | `_cleanup_stale_pipelines` minimum children=2 | `kanban.py` | 613 | `if len(children) < 2: continue` — пайплайны с 1 ребёнком никогда не чистятся. |
| 16 | judge.prompt мёртвый код | `agents/judge.prompt` | весь | Файл не используется — промпт строится динамически в `ensemble.py:_build_judge_prompt()`. |
| 17 | ensemble config читается на каждую итерацию | `ensemble.py` | 85, 163, 191 | `read_ensemble_config()` вызывается в каждом `generate_candidates()`, `judge_candidates()`, `should_use_ensemble()` — YAML парсится многократно. |
| 18 | deterministic judge выбирает середину, не 0.7 | `ensemble.py` | 150 | `len(candidates)//2` даёт температуру ~0.7 только для n=5. Для n=3 → 0.5, n=7 → 0.9. |
| 19 | title parsing хрупкий | `kanban.py` | 670 | `title.replace("🔷  Пайплайн: ", "")` — зависит от точного emoji + пробелов. |
| 20 | multiple active pipelines | `kanban.py` | 653 | `parent_rows[0]` — берётся только первый. Остальные активные пайплайны орфанные. |

---

## 2. Приоритет фиксов

### Фаза 1: Crash & Blockers (P0 — 4 бага)

| Порядок | Баг | Почему сначала |
|---------|-----|----------------|
| **1.1** | #1 — coder не перезапускается | **Критично**: convergence cycle сломан полностью. Без этого ни один пайплайн не может делать >1 раунда. |
| **1.2** | #3 — LLM Judge фальшивый winner | **Критично**: ensemble mode возвращает рандом — пользователь получает неверный результат без предупреждения. |
| **1.3** | #4 — Flash без prompt | **Критично**: Flash-агенты (finder, analyst, coder, tester, etc.) работают без контекста — результат бесполезен. |
| **1.4** | #2 — HERMES_HOME | Важно, но менее срочно: если HERMES_HOME не установлен, работает fallback. |

### Фаза 2: Диагностика & State (P1 — 7 багов)

| Порядок | Баг | Почему |
|---------|-----|--------|
| **2.1** | #5 — stack trace в handler'ах | **Без этого нельзя диагностировать другие баги в проде.** |
| **2.2** | #8 — mutation state по ссылке | **Корень проблем с convergence/reopen cycle** — state портится при каждом evaluate. |
| **2.3** | #6 — scan_board теряет findings | После рестарта все findings пропадают → convergence не может определить stuck vs continue. |
| **2.4** | #11 — maxed_out не закрывает детей | Dashboard показывает running задачи у мёртвого пайплайна. |
| **2.5** | #9 — 'док' false positive | classify ошибается — user ждёт security audit, получает документацию. |
| **2.6** | #7 — metadata игнорируется | Потеря данных при завершении. |
| **2.7** | #10 — мёртвый заголовок | Косметика, но баг в промпте = баг в результате. |

### Фаза 3: Quality (P2 — 9 багов)

| Порядок | Баг | Почему |
|---------|-----|--------|
| 3.1 | #18 — deterministic judge не 0.7 | Ensemble accuracy страдает. |
| 3.2 | #13 — пустой findings → convergence | Ложное завершение пайплайна. |
| 3.3 | #17 — config читается на каждую итерацию | Перф (микрооптимизация). |
| 3.4 | #14 — blocked не найден | State reconstruction неполный. |
| 3.5 | #19 — title parsing хрупкий | Ломается при смене emoji. |
| 3.6 | #20 — multiple active pipelines | При потере state. |
| 3.7 | #16 — judge.prompt мёртвый код | Удалить неиспользуемый файл. |
| 3.8 | #15 — cleanup children minimum | Мешает очистке. |
| 3.9 | #12 — false positive import os | Не фиксить (false positive). |

---

## 3. Набор минимальных PR-изменений

### PR #1: Bugfix — Convergence Cycle (P0 #1, #8, #4, P1 #11)

**Файлы:** `kanban.py`, `__init__.py`

**Изменения:**

#### 3.1.1 Новая функция `reopen(task_id)` в `kanban.py`

```python
def reopen(task_id: str) -> bool:
    """Re-open a 'done' task for a new convergence round.
    
    Transitions done → ready and resets assignee so the orchestrator
    can pick it up again. Returns True if succeeded.
    """
    return _sqlite_update(
        "UPDATE tasks SET status='ready', assignee=NULL, "
        "last_heartbeat_at=NULL WHERE id=? AND status='done'",
        (task_id,),
    )
```

#### 3.1.2 `on_convergence('continue')` → `reopen()` вместо `unblock()`

```python
# kanban.py, on_convergence(), decision == "continue"
elif decision == "continue":
    coder_id = task_ids.get("coder")
    if coder_id:
        reopen(coder_id)  # done→ready вместо unblock (todo/blocked→ready)
        comment(parent_id, f"🔄 Раунд {round_num}: @coder перезапущен "
                f"({len(findings)} findings)")
```

#### 3.1.3 `maxed_out` закрывает детей

```python
# kanban.py, on_convergence(), decision == "maxed_out"
elif decision == "maxed_out":
    metadata = {"decision": "maxed_out", "round": round_num,
                "p0": p0, "p1": p1, "p2": p2}
    complete(parent_id, result_summary=f"Maxed out: {reason}", metadata=metadata)
    for agent, tid in task_ids.items():
        complete(tid, result_summary=f"❌ @{agent} maxed out")
```

#### 3.1.4 Flash-агенты получают prompt (P0 #4)

```python
# __init__.py, handle_run_agent()
# Для direct-агентов: строим prompt перед return
ctx = context_override if context_override is not None else state.get("context", {})
request = state.get("request", "")
category = state.get("category", "")
prompt_result = _build_agent_prompt(agent_id, ctx, request, category)
flash_prompt = prompt_result.get("prompt") if "error" not in prompt_result else None

return json.dumps({
    "agent_id": agent_id,
    "directive": directive,
    "tool_hint": tool_hint,
    "provider": provider,
    "model": model,
    "prompt": flash_prompt,  # было None, теперь реальный prompt
    "call_args": None,
    "state": state,
}, ensure_ascii=False)
```

#### 3.1.5 Deep copy state в `handle_convergence` (P1 #8)

```python
# __init__.py, handle_convergence()
import copy
state = copy.deepcopy(args["state"])  # не мутируем оригинал
```

### PR #2: LLM Judge & Ensemble (P0 #3, P2 #18, #17)

**Файлы:** `ensemble.py`

**Изменения:**

#### 3.2.1 LLM Judge реально оценивает (P0 #3)

Убрать заглушку. `judge_candidates(mode="llm")` должен либо:
(a) Синхронно вызвать LLM через `delegate_task`, или
(b) Вернуть `judge_prompt` для асинхронного вызова, но в winner_id поставить `null`.

Вариант (b) — минимальное изменение:

```python
if judge_mode == "llm":
    prompt = _build_judge_prompt(request, candidates)
    judge_cfg = judge_config or {}
    return {
        "winner_id": None,  # было фальшивое, теперь null
        "rationale": "LLM Judge evaluation needed — delegate with judge_prompt",
        "mode": "llm",
        "judge_prompt": prompt,
        "judge_provider": judge_cfg.get("provider", "polza"),
        "judge_model": judge_cfg.get("model", "deepseek-v4-flash"),
    }
```

#### 3.2.2 Deterministic judge → температура 0.7 (P2 #18)

```python
# Вместо len(candidates)//2 — найти ближайшую к 0.7
if judge_mode == "deterministic" or len(candidates) <= 2:
    best = min(candidates,
               key=lambda c: abs(c.get("temperature", 0.7) - 0.7))
    idx = candidates.index(best)
    winner = candidates[idx]
```

#### 3.2.3 Кэш конфига (P2 #17)

```python
from functools import lru_cache

@lru_cache(maxsize=1)
def read_ensemble_config_cached() -> dict:
    return _read_ensemble_config_impl()

# generate_candidates() и judge_candidates() используют cached версию
```

### PR #3: Stack traces & Diagnostics (P1 #5, #6, #7)

**Файлы:** `__init__.py`, `kanban.py`

**Изменения:**

#### 3.3.1 Все handler'ы с `traceback.format_exc()`

Паттерн для 8 handler'ов:

```python
except Exception as e:
    return json.dumps({
        "error": str(e),
        "traceback": traceback.format_exc(),
    }, ensure_ascii=False)
```

Затрагивает: `handle_save`, `handle_load`, `handle_clear`, `handle_resume`, `handle_advance`, `handle_model`, `handle_ensemble_run`, `handle_ensemble_judge`.

#### 3.3.2 `scan_board()` восстанавливает findings и round (P1 #6)

```python
# После реконструкции state — парсим комментарии parent
def _extract_findings_from_comments(parent_id: str) -> tuple[int, list]:
    """Извлечь round и findings из комментариев к parent task."""
    comments = _sqlite_select(
        "SELECT body FROM task_comments WHERE task_id=? ORDER BY created_at DESC LIMIT 1",
        (parent_id,),
    )
    if not comments:
        return (0, [])
    body = comments[0].get("body", "")
    # Парсим "Раунд: N" и "P0: N P1: N P2: N"
    round_match = re.search(r"Раунд: (\d+)", body)
    round_num = int(round_match.group(1)) if round_match else 0
    # findings можно восстановить из последнего convergence comment
    # или хранить findings в отдельном comment
    return (round_num, [])
```

#### 3.3.3 `complete()` сохраняет metadata (P1 #7)

```python
def complete(task_id: str, result_summary: str = "",
             metadata: dict | None = None) -> bool:
    ok = _sqlite_update(...)
    if ok and result_summary:
        summary = result_summary
        if metadata:
            summary += f"\n\n**Metadata:** {json.dumps(metadata, ensure_ascii=False)}"
        _sqlite_update(
            "INSERT INTO task_comments (...) VALUES (...)",
            (task_id, summary, "pipeline-orchestrator"),
        )
    return ok
```

### PR #4: Classify & Prompts (P1 #9, #10)

**Файлы:** `classify.py`, `agents/integration.prompt`, `agents/judge.prompt`

**Изменения:**

#### 3.4.1 Убрать 'док' из DOCUMENTATION (P1 #9)

```python
# classify.py, CATEGORIES["DOCUMENTATION"]["keywords"]
# Убрать "док" — ловит docker, доклады
# Заменить на "документац" (уже есть), "доки" (сленг)
```

#### 3.4.2 Убрать мёртвый 'Full context' из integration.prompt (P1 #10)

Удалить строку `### Full context` из `agents/integration.prompt`.

#### 3.4.3 Удалить `judge.prompt` (P2 #16)

Файл мёртвый — удалить.

### PR #5: Stale pipelines & Robustness (P2 #13, #14, #15, #19, #20)

**Файлы:** `kanban.py`, `classify.py`

#### 3.5.1 Пустой findings → не convergence (P2 #13)

```python
# evaluate_convergence()
if findings is not None and len(findings) == 0 and state.get("round", 0) == 0:
    return {
        "decision": "continue",
        "reason": "No findings yet — need at least one analysis round",
        ...
    }
```

#### 3.5.2 `_cleanup_stale_pipelines` — minimum children = 1 (P2 #15)

```python
if len(children) < 1:  # было < 2
    continue
```

#### 3.5.3 Title parsing regex (P2 #19)

```python
import re
match = re.match(r"🔷\s*Пайплайн:\s*(.*)", title)
request = match.group(1) if match else title
```

#### 3.5.4 Multiple active pipelines — warn (P2 #20)

```python
if len(parent_rows) > 1:
    logger.warning("Found %d active pipeline(s) — using most recent", len(parent_rows))
```

---

## 4. Архитектура convergence/reopen cycle

### 4.1 Текущая проблема

```
[coder runs] → status: 'done'
     ↓
convergence → 'continue'
     ↓
unblock(coder_id) → promote() → UPDATE ... WHERE status IN ('todo','blocked')
     ↓
НЕТ ЭФФЕКТА — coder в 'done', не matched
     ↓
Пассивное ожидание → orchestrator видит 'done' → тупик
```

### 4.2 Исправленный цикл

```
[coder runs] → status: 'done'
     ↓
convergence → 'continue'
     ↓
reopen(coder_id) → UPDATE ... WHERE status='done' → status='ready'
     ↓
orchestrator видит 'ready' → claim → 'running' → coder запускается
     ↓
[coder runs с новыми findings] → status: 'done'
     ↓
convergence → 'continue' ИЛИ 'converged' ИЛИ 'stuck' ИЛИ 'maxed_out'
     ↓
                  ┌──────┬────────┬──────────┬──────────┐
                  ↓      ↓        ↓          ↓
              continue converged stuck   maxed_out
                  │        │        │          │
              reopen() complete() block()  complete()
              coder    parent+    parent    parent+
              →ready   children  →blocked   children
                       →done               →done
```

### 4.3 State mutation protection

**Проблема:** `evaluate_convergence()` пишет `findings`, `findings_fingerprint`, `round` в переданный dict.

**Решение:** В `handle_convergence()` делать `copy.deepcopy(state)` перед передачей. В `evaluate_convergence()` создать новый dict для хранения результатов мутации, не трогать входной.

```python
def evaluate_convergence(state: dict, findings: list | None = None) -> dict:
    """Чистая функция — не мутирует входной state."""
    new_state = dict(state)  # поверхностная копия для round/findings
    if findings is not None:
        curr_fp = new_state.get("findings_fingerprint", "")
        new_state["findings"] = list(findings)
        new_state["findings_fingerprint"] = _compute_fingerprint(...)
        new_state["prev_findings_fingerprint"] = curr_fp
        new_state["round"] = new_state.get("round", 0) + 1
    
    # ... вычисление decision ...
    
    return {
        "decision": ...,
        "reason": ...,
        "round": new_state.get("round", 0),
        "p0_count": ..., "p1_count": ..., "p2_count": ...,
        "_new_state": new_state,  # оркестратор сам решит, сохранять или нет
    }
```

### 4.4 Findings persistence после рестарта

**Проблема:** `scan_board()` теряет findings.

**Решение:** Хранить findings как JSON-комментарий на родительской таске после каждой convergence. `scan_board()` парсит последний convergence comment.

```python
# on_convergence() — сохраняем findings в parent comment
findings_json = json.dumps(state.get("findings", []), ensure_ascii=False)
comment(parent_id, 
    f"🔍 **Конвергенция: {decision}**\n"
    f"Раунд: {round_num}  |  P0: {p0}  P1: {p1}  P2: {p2}\n"
    f"{reason}\n\n"
    f"**Findings JSON:**\n```json\n{findings_json}\n```")
```

```python
# scan_board() — парсим JSON из коммента
def _find_last_findings(parent_id: str) -> list:
    comments = _sqlite_select(
        "SELECT body FROM task_comments WHERE task_id=? "
        "AND body LIKE '%Findings JSON:%' ORDER BY created_at DESC LIMIT 1",
        (parent_id,),
    )
    if not comments:
        return []
    body = comments[0]["body"]
    m = re.search(r"```json\n(.+?)\n```", body, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except (json.JSONDecodeError, Exception):
            return []
    return []
```

### 4.5 Re-open multiple agents (гибкость)

Не только `coder` — convergence может решить перезапустить любого агента. Добавить `reopen_agent` в convergence result:

```python
# evaluate_convergence() может вернуть
{
    "decision": "continue",
    "reason": "...",
    "reopen_agent": "coder",  # или "fixer", "debugger" — кто должен перезапуститься
    ...
}
```

`on_convergence()` использует `reopen_agent` из результата:

```python
if decision == "continue":
    reopen_agent = convergence_result.get("reopen_agent", "coder")
    agent_id = task_ids.get(reopen_agent)
    if agent_id:
        reopen(agent_id)
```

### 4.6 Защита от пустого findings → ложного converged

```python
# evaluate_convergence(), в начале
if findings is not None and len(findings) == 0 and state.get("round", 0) == 0:
    return {"decision": "continue",
            "reason": "No findings yet — analysis not complete",
            "round": 0, "p0_count": 0, "p1_count": 0, "p2_count": 0}
```

---

## 5. Разделение ответственности

### Отправить автору (akrhin) как PR описание

**PR #1: Bugfix — Convergence Cycle** — самое важное. Описание:

```
Fix 4 P0 bugs in convergence cycle:

1. **reopen()** — new function: done→ready. `on_convergence('continue')` теперь
   перезапускает coder через reopen(), а не unblock()/promote().
   
2. **Flash-агенты получают prompt** — `pipeline_run_agent` для direct-агентов
   теперь строит prompt через _build_agent_prompt().

3. **state mutation** — `handle_convergence` делает copy.deepcopy перед мутацией.

4. **maxed_out** закрывает дочерние задачи.

5. **metadata** в complete() сохраняется в комментарий.
```

**PR #2: LLM Judge — честный результат**

```
1. LLM Judge возвращает `winner_id: null` вместо фальшивого middle candidate.
   Оркестратор видит null и знает, что нужно делегировать judge_prompt.

2. Deterministic judge выбирает candidate с температурой, ближайшей к 0.7,
   вместо механического len(candidates)//2.

3. Ensemble config кэшируется (lru_cache).
```

**PR #3: Stack traces & Diagnostics**

```
1. Все 8 handler'ов возвращают traceback.format_exc() в error-ответе.

2. scan_board() парсит последний convergence comment для восстановления
   findings и round после рестарта.
```

**PR #4: Classify & Prompts**

```
1. Убрать 'док' из DOCUMENTATION keywords (false positive на docker/доклады).

2. Убрать мёртвый заголовок 'Full context' из integration.prompt.

3. Удалить мёртвый agents/judge.prompt.
```

**PR #5: Stale pipelines & Robustness**

```
1. Пустой findings больше не даёт false convergent.
2. _cleanup_stale minimum children=2 → 1.
3. Title parsing через regex.
4. Warning при multiple active pipelines.
```

### Что фиксить у себя (локально)

1. **`$HERMES_HOME` в systemd** — если проблема в окружении (а не в коде):
   - systemd unit → добавить `Environment=HERMES_HOME=/home/user/.hermes`
   - Или читать из `~/.hermes/config.yaml` если `$HERMES_HOME` не установлен:
     ```python
     def _db_path() -> str:
         base = os.environ.get("HERMES_HOME")
         if not base:
             # Fallback: читаем из HERMES config.yaml
             try:
                 with open(os.path.expanduser("~/.hermes/config.yaml")) as f:
                     cfg = yaml.safe_load(f)
                     if isinstance(cfg, dict) and "hermes_home" in cfg:
                         base = cfg["hermes_home"]
             except Exception:
                 pass
         base = base or os.path.expanduser("~/.hermes")
         return os.path.join(base, "kanban", "boards", "pipeline", "kanban.db")
     ```

2. **Dashboard** — если dashboard независимый:
   - Проверить, что `/home/user/git/pipeline-dashboard/server.py` тоже использует `HERMES_HOME`.
   - Если нет — добавить.

---

## 6. Сводка изменений по файлам

| Файл | Изменения | PR |
|------|-----------|-----|
| `kanban.py` | `reopen()` + `on_convergence(continue→reopen)` + `maxed_out→close children` + `_extract_findings_from_comments` + пустой findings guard + `_cleanup_stale min_children=1` + title regex | #1, #3, #5 |
| `__init__.py` | Flash prompt fix + deepcopy in converge + stack traces в 8 handlers | #1, #3 |
| `ensemble.py` | LLM Judge честный null + deterministic 0.7 + lru_cache + remove заглушку | #2 |
| `classify.py` | Remove 'док' from DOCUMENTATION + word-boundary fix | #4 |
| `agents/integration.prompt` | Remove dead "Full context" header | #4 |
| `agents/judge.prompt` | Delete file (dead code) | #4 |
| `plugin.yaml` | Bump version → 3.1.2 | все |
