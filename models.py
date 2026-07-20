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
    "finder": {"provider": "direct", "model": "deepseek-v4-flash"},
    "analyst": {"provider": "direct", "model": "deepseek-v4-flash"},
    "planner": {"provider": "direct", "model": "deepseek-v4-flash"},
    "coder": {"provider": "direct", "model": "deepseek-v4-flash"},
    "fixer": {"provider": "direct", "model": "deepseek-v4-flash"},
    "refactorer": {"provider": "direct", "model": "deepseek-v4-flash"},
    "tester": {"provider": "direct", "model": "deepseek-v4-flash"},
    "debugger": {"provider": "direct", "model": "deepseek-v4-flash"},
    "documenter": {"provider": "direct", "model": "deepseek-v4-flash"},
    "devops": {"provider": "direct", "model": "deepseek-v4-flash"},
    "optimizer": {"provider": "direct", "model": "deepseek-v4-flash"},
    "architect": {"provider": "delegate", "model": "deepseek-v4-pro"},
    "reviewer": {"provider": "delegate", "model": "deepseek-v4-pro"},
    "security": {"provider": "delegate", "model": "deepseek-v4-pro"},
    "integration": {"provider": "delegate", "model": "deepseek-v4-pro"},
    "researcher": {"provider": "delegate_free", "model": "openrouter/free"},
}

# Провайдер-типы, для которых defaults применимы
VALID_PROVIDER_TYPES = frozenset({"direct", "delegate", "delegate_free"})


def _get_config_path() -> Path:
    """Путь к конфигу плагина: ~/.hermes/plugins/pipeline/config.yaml
    с поддержкой profile-специфичных конфигов (config.<profile>.yaml).

    Приоритет:
      1. config.<profile>.yaml если HERMES_PROFILE установлен и файл существует
      2. config.yaml (по умолчанию)
    Не читает главный config.yaml Hermes, чтобы не засорять его.
    """
    hermes_home = os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes"))
    base_dir = Path(hermes_home) / "plugins" / "pipeline"

    profile = os.environ.get("HERMES_PROFILE", "")
    if profile:
        profile_path = base_dir / f"config.{profile}.yaml"
        if profile_path.exists():
            return profile_path

    return base_dir / "config.yaml"


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
    Сопоставление по оригинальному provider из BUILTIN_MODEL_MAP — не по текущему.
    Иначе если defaults меняет provider с delegate->direct, следующий defaults-bлок
    для direct случайно зацепит уже изменённого агента.
    """
    for provider_type, override in defaults.items():
        if provider_type not in VALID_PROVIDER_TYPES:
            logger.warning("Unknown provider type in defaults: %s", provider_type)
            continue
        if not isinstance(override, dict):
            continue

        for agent_id, routing in model_map.items():
            # Сопоставляем по оригнальному provider из BUILTIN, не по текущему
            original = BUILTIN_MODEL_MAP.get(agent_id, {}).get("provider")
            if original == provider_type:
                if "provider" in override:
                    routing["provider"] = override["provider"]
                if "model" in override:
                    routing["model"] = override["model"]


def _merge_agents(
    model_map: dict[str, dict[str, str]],
    agents: dict[str, dict[str, str]],
) -> None:
    """Применить per-agent overrides к MODEL_MAP in-place."""
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
    model_map = {agent_id: dict(routing) for agent_id, routing in BUILTIN_MODEL_MAP.items()}

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
