# PLAN3 — Вынос `MODEL_MAP` из хардкода в `~/.hermes/config.yaml`

**Проблема:** `MODEL_MAP` на 17 агентов жёстко зашит в `__init__.py` (строка 360).
Чтобы сменить модель для агента или добавить нового, нужно править код плагина и рестартовать
сессию. Решение: вынести конфигурацию моделей в `~/.hermes/config.yaml` с fallback на хардкод.

**Scope:** новый модуль `models.py`, правки `__init__.py`, `AGENTS.md`, `ARCHITECTURE.md`.

---

## 1. Текущая MODEL_MAP (as-is, line 360)

```python
MODEL_MAP = {
    "finder":      {"provider": "direct", "model": "deepseek-v4-flash"},
    "analyst":     {"provider": "direct", "model": "deepseek-v4-flash"},
    "planner":     {"provider": "direct", "model": "deepseek-v4-flash"},
    "coder":       {"provider": "direct", "model": "deepseek-v4-flash"},
    "editor":      {"provider": "direct", "model": "deepseek-v4-flash"},
    "fixer":       {"provider": "direct", "model": "deepseek-v4-flash"},
    "refactorer":  {"provider": "direct", "model": "deepseek-v4-flash"},
    "tester":      {"provider": "direct", "model": "deepseek-v4-flash"},
    "debugger":    {"provider": "direct", "model": "deepseek-v4-flash"},
    "documenter":  {"provider": "direct", "model": "deepseek-v4-flash"},
    "devops":      {"provider": "direct", "model": "deepseek-v4-flash"},
    "optimizer":   {"provider": "direct", "model": "deepseek-v4-flash"},
    "architect":   {"provider": "delegate", "model": "deepseek-v4-pro"},
    "reviewer":    {"provider": "delegate", "model": "deepseek-v4-pro"},
    "security":    {"provider": "delegate", "model": "deepseek-v4-pro"},
    "integration": {"provider": "delegate", "model": "deepseek-v4-pro"},
    "researcher":  {"provider": "delegate_free", "model": "openrouter/free"},
}
```

Три провайдер-типа: `direct` (12 агентов), `delegate` (4 агента), `delegate_free` (1 агент).

---

## 2. Формат YAML-конфига в `~/.hermes/config.yaml`

### 2.1 Секция `pipeline.models`

Секция опциональна. Если отсутствует — работает текущий хардкод (полная обратная совместимость).

```yaml
pipeline:
  models:
    # ── Default overrides для каждого провайдер-типа ──
    # Любой агент matching provider-type получает эти provider/model.
    # Поля provider и/или model опциональны — не указано = из хардкода.
    defaults:
      direct:
        provider: direct        # можно опустить, если не меняется
        model: deepseek-v4-flash # можно опустить
      delegate:
        provider: delegate
        model: deepseek-v4-pro
      delegate_free:
        provider: delegate_free
        model: openrouter/free

    # ── Per-agent overrides (высший приоритет) ──
    # Можно переопределить provider, model, или оба.
    # Если provider не указан — сохраняется из defaults или хардкода.
    agents:
      coder:
        model: deepseek-v4-pro       # только модель
      tester:
        provider: delegate            # сменить provider + модель
        model: deepseek-v4-pro
      researcher:
        model: perplexity/sonar-pro   # другая free-модель
      architect:
        model: deepseek-v4-flash      # даже Pro → Flash (для тестов)
```

### 2.2 Валидация и ограничения

- `provider` должен быть одним из `direct`, `delegate`, `delegate_free`.
- `model` — любая непустая строка (валидация на совместимость с провайдером — вне скоупа).
- Неизвестные ключи на верхнем уровне `pipeline.models` — **игнорируются** (forward compat).
- Неизвестные `agent_id` в `agents.*` — **логируются warning, игнорируются** (не падают).

### 2.3 Полные примеры

**Пример A — только defaults (смена всех моделей разом):**
```yaml
pipeline:
  models:
    defaults:
      direct:
        model: deepseek-v4-flash
      delegate:
        model: deepseek-v4-pro
      delegate_free:
        model: openrouter/free
```
→ все 17 агентов получают модели из defaults. Per-agent overrides пуст.

**Пример B — per-agent точечная настройка:**
```yaml
pipeline:
  models:
    agents:
      coder:
        model: deepseek-v4-pro
      tester:
        model: deepseek-v4-flash
```
→ только `coder` и `tester` меняются. Остальные из хардкода. `defaults` не заданы.

**Пример C — downgrade Pro-агентов в Flash (для dev/тестов):**
```yaml
pipeline:
  models:
    defaults:
      delegate:
        provider: direct
        model: deepseek-v4-flash
```
→ все Pro-агенты (architect, reviewer, security, integration) становятся direct:Flash.

**Пример D — полный кастом (собственный провайдер):**
```yaml
pipeline:
  models:
    defaults:
      direct:
        model: openrouter/anthropic/claude-sonnet-4
      delegate:
        provider: delegate
        model: openrouter/anthropic/claude-opus-4
      delegate_free:
        model: openrouter/free
    agents:
      researcher:
        model: openrouter/perplexity/sonar-pro
```

---

## 3. API лоадера: `models.py`

### 3.1 Новый модуль: `hermes_pipeline/models.py`

```python
"""
Model configuration loader for Pipeline Plugin.
Reads pipeline.models from ~/.hermes/config.yaml,
merges with built-in defaults, returns final MODEL_MAP.
"""

import logging
import os
from pathlib import Path
from typing import Any

import yaml  # PyYAML всегда доступен в Hermes-окружении

logger = logging.getLogger(__name__)

# ── Built-in fallback MODEL_MAP (неизменный хардкод) ──

BUILTIN_MODEL_MAP: dict[str, dict[str, str]] = {
    "finder":      {"provider": "direct", "model": "deepseek-v4-flash"},
    "analyst":     {"provider": "direct", "model": "deepseek-v4-flash"},
    "planner":     {"provider": "direct", "model": "deepseek-v4-flash"},
    "coder":       {"provider": "direct", "model": "deepseek-v4-flash"},
    "editor":      {"provider": "direct", "model": "deepseek-v4-flash"},
    "fixer":       {"provider": "direct", "model": "deepseek-v4-flash"},
    "refactorer":  {"provider": "direct", "model": "deepseek-v4-flash"},
    "tester":      {"provider": "direct", "model": "deepseek-v4-flash"},
    "debugger":    {"provider": "direct", "model": "deepseek-v4-flash"},
    "documenter":  {"provider": "direct", "model": "deepseek-v4-flash"},
    "devops":      {"provider": "direct", "model": "deepseek-v4-flash"},
    "optimizer":   {"provider": "direct", "model": "deepseek-v4-flash"},
    "architect":   {"provider": "delegate", "model": "deepseek-v4-pro"},
    "reviewer":    {"provider": "delegate", "model": "deepseek-v4-pro"},
    "security":    {"provider": "delegate", "model": "deepseek-v4-pro"},
    "integration": {"provider": "delegate", "model": "deepseek-v4-pro"},
    "researcher":  {"provider": "delegate_free", "model": "openrouter/free"},
}

# Провайдер-типы, для которых defaults применимы
VALID_PROVIDER_TYPES = frozenset({"direct", "delegate", "delegate_free"})


def _get_config_path() -> Path:
    """Путь к Hermes config.yaml."""
    hermes_home = os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes"))
    return Path(hermes_home) / "config.yaml"


def _read_config_section() -> dict[str, Any] | None:
    """Прочитать секцию pipeline.models из config.yaml.
    Возвращает None если файл отсутствует или секции нет.
    """
    config_path = _get_config_path()
    if not config_path.exists():
        logger.debug("Config file not found: %s", config_path)
        return None

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)
    except yaml.YAMLError as e:
        logger.warning("Failed to parse config.yaml: %s", e)
        return None
    except OSError as e:
        logger.warning("Failed to read config.yaml: %s", e)
        return None

    if not isinstance(raw, dict):
        return None

    pipeline_section = raw.get("pipeline")
    if not isinstance(pipeline_section, dict):
        return None

    models_section = pipeline_section.get("models")
    if not isinstance(models_section, dict):
        return None

    return models_section


def _merge_defaults(
    model_map: dict[str, dict[str, str]],
    defaults: dict[str, dict[str, str]],
) -> None:
    """Применить defaults к MODEL_MAP in-place.
    Для каждого агента: если его provider совпадает с ключом в defaults —
    обновить те поля, которые заданы в defaults.
    """
    for provider_type, override in defaults.items():
        if provider_type not in VALID_PROVIDER_TYPES:
            logger.warning("Unknown provider type in defaults: %s", provider_type)
            continue
        if not isinstance(override, dict):
            continue

        for agent_id, routing in model_map.items():
            if routing["provider"] == provider_type:
                if "provider" in override:
                    routing["provider"] = override["provider"]
                if "model" in override:
                    routing["model"] = override["model"]


def _merge_agents(
    model_map: dict[str, dict[str, str]],
    agents: dict[str, dict[str, str]],
) -> None:
    """Применить per-agent overrides к MODEL_MAP in-place.
    """
    for agent_id, override in agents.items():
        if agent_id not in model_map:
            logger.warning("Unknown agent in config pipeline.models.agents: %s", agent_id)
            continue
        if not isinstance(override, dict):
            continue

        if "provider" in override:
            model_map[agent_id]["provider"] = override["provider"]
        if "model" in override:
            model_map[agent_id]["model"] = override["model"]


def load_model_config() -> dict[str, dict[str, str]]:
    """Загрузить MODEL_MAP: config.yaml → merge с хардкодом.

    Merge strategy (in priority order, highest first):
      1. pipeline.models.agents.<agent_id>   — per-agent override
      2. pipeline.models.defaults.<type>      — provider-type default override
      3. BUILTIN_MODEL_MAP                    — hardcoded fallback

    Returns:
        dict: Рабочая MODEL_MAP (shallow copy, оригинал BUILTIN_MODEL_MAP не мутирует).
    """
    # 1. Копируем хардкод (чтобы не мутировать BUILTIN_MODEL_MAP)
    model_map = {
        agent_id: dict(routing) for agent_id, routing in BUILTIN_MODEL_MAP.items()
    }

    # 2. Читаем config.yaml
    config_section = _read_config_section()
    if config_section is None:
        return model_map  # ← чистый fallback

    # 3. Применяем defaults (приоритет 2)
    defaults = config_section.get("defaults")
    if isinstance(defaults, dict):
        _merge_defaults(model_map, defaults)

    # 4. Применяем per-agent overrides (приоритет 1)
    agents = config_section.get("agents")
    if isinstance(agents, dict):
        _merge_agents(model_map, agents)

    return model_map
```

### 3.2 Сигнатура и гарантии

| Свойство | Поведение |
|----------|-----------|
| **Всегда возвращает dict** | Никогда не падает, даже при битом YAML |
| **Не мутирует BUILTIN_MODEL_MAP** | Возвращает shallow copy |
| **Config → merge → result** | Порядок: хардкод → defaults → agents |
| **Неизвестные ключи** | Warning в лог, игнорируются |
| **Отсутствует config.yaml** | Возвращает копию BUILTIN_MODEL_MAP |
| **Битый YAML** | Warning + возвращает копию BUILTIN_MODEL_MAP |
| **Пустая секция `pipeline.models: {}`** | Возвращает копию BUILTIN_MODEL_MAP |

### 3.3 Merge-стратегия (визуально)

```
BUILTIN_MODEL_MAP (hardcoded)
    │
    ▼
[apply defaults.direct]   → меняет provider/model у всех direct-агентов
[apply defaults.delegate] → меняет provider/model у всех delegate-агентов
[apply defaults.delegate_free] → ... у delegate_free
    │
    ▼
[apply agents.coder]      → точечный override для coder
[apply agents.tester]     → точечный override для tester
[apply agents.*]
    │
    ▼
FINAL MODEL_MAP
```

Важно: `defaults` применяется ДО `agents`, поэтому per-agent override всегда выигрывает.

Пример конфликта:
```yaml
pipeline:
  models:
    defaults:
      direct:
        model: deepseek-v4-flash
    agents:
      coder:
        model: deepseek-v4-pro
```
→ coder получит `deepseek-v4-pro` (agents priority > defaults).

---

## 4. Изменения в `__init__.py`

### 4.1 Замена `MODEL_MAP` (строка 360–378)

```diff
-MODEL_MAP = {
-    "finder":      {"provider": "direct", "model": "deepseek-v4-flash"},
-    ...
-    "researcher":  {"provider": "delegate_free", "model": "openrouter/free"},
-}
+from .models import load_model_config
+
+MODEL_MAP = load_model_config()
```

Хардкод `BUILTIN_MODEL_MAP` живёт в `models.py`, а `__init__.py` просто вызывает лоадер.
`handle_model` и `handle_run_agent` продолжают читать `MODEL_MAP` — **без изменений**.

### 4.2 Добавить импорт в начале

```diff
 import json
 import os
 import sys
 import traceback
+from . import models  # noqa: F401 — side-effect: MODEL_MAP
```

Или просто:
```diff
+from .models import load_model_config
```

### 4.3 `handle_model` и `handle_run_agent` — без изменений

Оба хендлера читают `MODEL_MAP` как модульную переменную. Значение загружается один раз при импорте плагина. Менять код хендлеров не нужно.

### 4.4 `register()` — без изменений

`register()` не трогает `MODEL_MAP`.

---

## 5. Файл `models.py` в структуре проекта

```
hermes-pipeline-plugin/
├── ARCHITECTURE.md
├── AGENTS.md
├── README.md
├── plugin.yaml
├── __init__.py          ← import load_model_config from models.py
├── models.py            ← NEW: BUILTIN_MODEL_MAP + _read_config + _merge_* + load_model_config()
├── classify.py
├── kanban.py
├── agents/
├── tests/
│   ├── test_classify.py
│   ├── test_init.py
│   ├── test_kanban_convergence.py
│   └── test_models.py   ← NEW: тесты для load_model_config
```

---

## 6. Тестирование: `tests/test_models.py`

### 6.1 Тест-кейсы

| # | Сценарий | Проверка |
|---|----------|----------|
| 1 | Нет config.yaml | `load_model_config()` возвращает копию BUILTIN_MODEL_MAP |
| 2 | config.yaml без `pipeline.models` | То же |
| 3 | `pipeline.models: {}` | То же |
| 4 | `defaults.direct.model: x` | Все direct-агенты получают model=x |
| 5 | `agents.coder.model: x` | Только coder меняет модель |
| 6 | `defaults` + `agents` конфликт | agents выигрывает |
| 7 | Битый YAML | Fallback, warning в лог |
| 8 | Неизвестный agent_id в agents | Warning, игнорируется |
| 9 | Неизвестный provider_type в defaults | Warning, игнорируется |
| 10 | BUILTIN_MODEL_MAP не мутируется | После вызова `load_model_config()` оригинал не изменён |

### 6.2 Реализация тестов (паттерн: мок YAML, не реальный config.yaml)

```python
"""Tests for models.py — MODEL_MAP loading and merge logic."""

import logging
import pytest
from unittest import mock

from hermes_pipeline import models


class TestLoadModelConfig:
    """Unit tests for load_model_config()."""

    def test_no_config_file(self):
        """If config.yaml doesn't exist → return copy of BUILTIN_MODEL_MAP."""
        with mock.patch.object(models, "_read_config_section", return_value=None):
            result = models.load_model_config()

        assert result == models.BUILTIN_MODEL_MAP
        # Проверяем что это копия, не тот же объект
        assert result is not models.BUILTIN_MODEL_MAP
        # И что мутация result не трогает оригинал
        result["finder"]["model"] = "changed"
        assert models.BUILTIN_MODEL_MAP["finder"]["model"] == "deepseek-v4-flash"

    def test_defaults_direct_model_override(self):
        """defaults.direct.model should apply to all direct agents."""
        section = {"defaults": {"direct": {"model": "deepseek-v4-super"}}}
        with mock.patch.object(models, "_read_config_section", return_value=section):
            result = models.load_model_config()

        for agent_id in ["finder", "analyst", "planner", "coder"]:
            assert result[agent_id]["model"] == "deepseek-v4-super"
            assert result[agent_id]["provider"] == "direct"  # provider unchanged

    def test_defaults_delegate_provider_and_model_override(self):
        """defaults.delegate can change both provider and model."""
        section = {
            "defaults": {"delegate": {"provider": "direct", "model": "deepseek-v4-flash"}}
        }
        with mock.patch.object(models, "_read_config_section", return_value=section):
            result = models.load_model_config()

        for agent_id in ["architect", "reviewer", "security", "integration"]:
            assert result[agent_id]["provider"] == "direct"
            assert result[agent_id]["model"] == "deepseek-v4-flash"

    def test_agents_override_single(self):
        """agents.coder overrides only coder."""
        section = {"agents": {"coder": {"model": "deepseek-v4-pro"}}}
        with mock.patch.object(models, "_read_config_section", return_value=section):
            result = models.load_model_config()

        assert result["coder"]["model"] == "deepseek-v4-pro"
        # Остальные direct не тронуты
        assert result["finder"]["model"] == "deepseek-v4-flash"

    def test_agents_wins_over_defaults(self):
        """Per-agent override has higher priority than defaults."""
        section = {
            "defaults": {"direct": {"model": "default-model"}},
            "agents": {"coder": {"model": "agent-specific-model"}},
        }
        with mock.patch.object(models, "_read_config_section", return_value=section):
            result = models.load_model_config()

        # coder — agents priority
        assert result["coder"]["model"] == "agent-specific-model"
        # остальные direct — defaults priority
        assert result["finder"]["model"] == "default-model"

    def test_agents_unknown_agent_id_logs_warning(self, caplog):
        """Unknown agent_id in agents section triggers warning."""
        section = {"agents": {"nonexistent_agent": {"model": "x"}}}
        with mock.patch.object(models, "_read_config_section", return_value=section):
            with caplog.at_level(logging.WARNING):
                result = models.load_model_config()

        assert "nonexistent_agent" in caplog.text
        # MODEL_MAP unaffected
        assert result == models.BUILTIN_MODEL_MAP

    def test_unknown_provider_type_in_defaults_logs_warning(self, caplog):
        """Unknown provider type in defaults is ignored with warning."""
        section = {"defaults": {"invalid_type": {"model": "x"}}}
        with mock.patch.object(models, "_read_config_section", return_value=section):
            with caplog.at_level(logging.WARNING):
                result = models.load_model_config()

        assert "invalid_type" in caplog.text
        assert result == models.BUILTIN_MODEL_MAP

    def test_researcher_defaults_delegate_free(self):
        """defaults.delegate_free should apply to researcher agent."""
        section = {
            "defaults": {
                "delegate_free": {"provider": "delegate", "model": "perplexity/sonar-pro"}
            }
        }
        with mock.patch.object(models, "_read_config_section", return_value=section):
            result = models.load_model_config()

        assert result["researcher"]["provider"] == "delegate"
        assert result["researcher"]["model"] == "perplexity/sonar-pro"

    def test_builtin_map_not_mutated(self):
        """After load_model_config() with config, BUILTIN_MODEL_MAP is pristine."""
        original = dict(models.BUILTIN_MODEL_MAP)
        section = {"defaults": {"direct": {"model": "totally-different"}}}
        with mock.patch.object(models, "_read_config_section", return_value=section):
            models.load_model_config()

        assert models.BUILTIN_MODEL_MAP == original

    def test_empty_config_section(self):
        """Empty pipeline.models: {} returns builtin copy."""
        with mock.patch.object(models, "_read_config_section", return_value={}):
            result = models.load_model_config()

        assert result == models.BUILTIN_MODEL_MAP
```

---

## 7. Изменения в `AGENTS.md`

### 7.1 Обновить секцию «Model Routing» (строка 39–44)

```diff
 ## Model Routing

-- **Flash** (`direct`): Finder, Analyst, Planner, Coder, Editor, Fixer, Refactorer, Tester, Debugger, Documenter, DevOps, Optimizer
-- **Pro** (`delegate_task`): Architect, Reviewer, Security, Integration
-- **Free** (`delegate_free`, OpenRouter): Researcher
+- Model routing настраивается в `~/.hermes/config.yaml` → секция `pipeline.models`.
+- Если секция отсутствует — используются значения по умолчанию (ниже).
+
+- **По умолчанию:**
+  - **Flash** (`direct`): Finder, Analyst, Planner, Coder, Editor, Fixer, Refactorer, Tester, Debugger, Documenter, DevOps, Optimizer
+  - **Pro** (`delegate`): Architect, Reviewer, Security, Integration
+  - **Free** (`delegate_free`): Researcher
+
+- **Конфигурация** (опционально, `~/.hermes/config.yaml`):
+  ```yaml
+  pipeline:
+    models:
+      defaults:          # default overrides by provider type
+        direct:
+          model: deepseek-v4-flash
+        delegate:
+          model: deepseek-v4-pro
+        delegate_free:
+          model: openrouter/free
+      agents:            # per-agent overrides (highest priority)
+        coder:
+          model: deepseek-v4-pro
+  ```
```

### 7.2 Обновить «Key Files» таблицу (строка 68–78)

```diff
 | `__init__.py` | Plugin core: 10 tools + register |
+| `models.py` | Model config loader: YAML → merge → MODEL_MAP |
 | `kanban.py` | Kanban API (create_tree, advance, converge, scan_board, resume) |
```

---

## 8. Изменения в `ARCHITECTURE.md`

### 8.1 Добавить секцию «Model Configuration» (после §Model Routing, строка 136)

```markdown
## Model Configuration (v2.2+)

MODEL_MAP больше не хардкодится в `__init__.py`. Вместо этого:

1. **`models.py`** содержит:
   - `BUILTIN_MODEL_MAP` — хардкодный fallback (текущие 17 агентов)
   - `load_model_config()` — читает `~/.hermes/config.yaml` → секция `pipeline.models`
   - Merge-логика: BUILTIN → defaults → agents

2. **`__init__.py`** вызывает `MODEL_MAP = load_model_config()` при импорте.

3. **Config merge priority:**
   1. `pipeline.models.agents.<agent_id>` — per-agent override (высший)
   2. `pipeline.models.defaults.<provider_type>` — default по типу провайдера
   3. `BUILTIN_MODEL_MAP` — хардкод (низший)

4. **Устойчивость:** если config.yaml отсутствует, битый, или секции нет —
   работает текущий хардкод без изменений.
```

### 8.2 Обновить «Files» дерево (строка 150–180)

```diff
 hermes-pipeline-plugin/
 ├── ARCHITECTURE.md            ← этот файл (v2.2)
 ├── AGENTS.md                  ← инструкции для агентов (v2.2)
 ├── README.md
 ├── plugin.yaml                ← манифест v2.2.0
-├── __init__.py                ← ядро: 10 хендлеров + регистрация
+├── __init__.py                ← ядро: 10 хендлеров + регистрация (MODEL_MAP из models.py)
+├── models.py                  ← NEW: MODEL_MAP loader (YAML config → merge)
 ├── classify.py
 ├── kanban.py
 ...
 ├── tests/
 │   ├── test_classify.py
 │   ├── test_init.py
 │   ├── test_kanban_convergence.py
+│   └── test_models.py         ← NEW: тесты для load_model_config
```

### 8.3 Обновить «Изменения» таблицу (строка 183–189)

```diff
 | 2026-07-19 | **v2.1.0**: +pipeline_run_agent (delegation package pattern), 10 tools |
+| 2026-07-19 | **v2.2.0**: MODEL_MAP → config.yaml (models.py) |
```

---

## 9. Порядок реализации

| # | Файл | Что | Зависит от |
|---|------|-----|-----------|
| 1 | `models.py` | Новый модуль: BUILTIN_MODEL_MAP + load_model_config() + merge helpers | — |
| 2 | `tests/test_models.py` | 10 unit-тестов на merge-логику | 1 |
| 3 | `__init__.py` | Убрать MODEL_MAP (17 строк), добавить `from .models import load_model_config` + `MODEL_MAP = load_model_config()` | 1 |
| 4 | `tests/test_init.py` | Проверить что handle_model/handle_run_agent работают после изменений | 3 |
| 5 | `plugin.yaml` | Bump версии 2.1.0 → 2.2.0 | — |
| 6 | `AGENTS.md` | Обновить Model Routing (+config example), Key Files таблицу | 2 |
| 7 | `ARCHITECTURE.md` | +Model Configuration секция, Files дерево, Changelog | 2 |
| 8 | `make test` / `ruff check` | Прогнать все тесты + линтер | 1–7 |

---

## 10. Pitfalls

1. **Hermes перезапуск нужен.** Плагин импортится один раз при старте сессии.
   `MODEL_MAP = load_model_config()` выполняется в момент импорта `__init__.py`.
   После изменения `config.yaml` нужен рестарт сессии (новый чат) — как и для любых
   правок плагина.

2. **Не менять BUILTIN_MODEL_MAP.** `load_model_config()` возвращает shallow copy через
   `{agent_id: dict(routing) for ...}`. Если вернуть ссылку на оригинал — `_merge_*`
   мутирует хардкод, и последующие вызовы вернут «грязный» словарь.

3. **Shallow copy достаточно.** Значения в MODEL_MAP — flat dicts `{"provider": str, "model": str}`,
   нет вложенных mutable объектов. `dict(routing)` создаёт независимую копию.

4. **YAML всегда доступен.** PyYAML есть в Hermes-окружении. Не нужно добавлять в зависимости —
   импорт `import yaml` не упадёт.

5. **Обратная совместимость.** Если `pipeline.models` нет в config.yaml — всё работает
   как раньше. Никаких breaking changes.

6. **Logging.** Использовать `logging.getLogger(__name__)` — сообщения попадут в
   общий лог Hermes. Warning при битом YAML или неизвестных ключах.

7. **Тесты не требуют Hermes runtime.** `test_models.py` мокает `_read_config_section()`
   и тестирует только merge-логику. Может запускаться в CI без Hermes.

8. **`register(ctx)` не меняется.** `ctx` не используется для конфигурации моделей.
   Конфиг читается из файловой системы, а не из Hermes API.

---

## 11. Проверка (после реализации)

```bash
cd ~/git/hermes-pipeline-plugin

# 1. Линтер
ruff check __init__.py models.py tests/test_models.py

# 2. Синтаксис
python3 -c "import ast; ast.parse(open('__init__.py').read()); print('__init__.py OK')"
python3 -c "import ast; ast.parse(open('models.py').read()); print('models.py OK')"

# 3. Тесты models.py (unit, без Hermes)
pytest tests/test_models.py -v

# 4. Все тесты
make test || echo "CI-only: requires hermes-agent runtime"

# 5. YAML валидация плагина
python3 -c "import yaml; yaml.safe_load(open('plugin.yaml')); print('plugin.yaml OK')"

# 6. Проверить что MODEL_MAP загружается (в Hermes-сессии)
hermes run "вызови agent_model для агента coder"  # должен вернуть model из config или default
```
