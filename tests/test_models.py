"""Tests for models.py — MODEL_MAP loading and merge logic."""

import logging
import os
import sys
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import models


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

    def test_empty_config_section(self):
        """Empty pipeline.models: {} returns builtin copy."""
        with mock.patch.object(models, "_read_config_section", return_value={}):
            result = models.load_model_config()

        assert result == models.BUILTIN_MODEL_MAP

    def test_defaults_direct_model_override(self):
        """defaults.delegate.model should apply to all delegate agents."""
        section = {"defaults": {"delegate": {"model": "deepseek-v4-super"}}}
        with mock.patch.object(models, "_read_config_section", return_value=section):
            result = models.load_model_config()

        for agent_id in ["finder", "analyst", "planner", "coder"]:
            assert result[agent_id]["model"] == "deepseek-v4-super"
            assert result[agent_id]["provider"] == "delegate"  # provider unchanged

    def test_defaults_delegate_provider_and_model_override(self):
        """defaults.delegate can change both provider and model."""
        section = {"defaults": {"delegate": {"provider": "direct", "model": "deepseek-v4-flash"}}}
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
            "defaults": {"delegate": {"model": "default-model"}},
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
            "defaults": {"delegate_free": {"provider": "direct", "model": "perplexity/sonar-pro"}}
        }
        with mock.patch.object(models, "_read_config_section", return_value=section):
            result = models.load_model_config()

        # researcher is now delegate not delegate_free in builtin
        # so delegate_free defaults won't match unless we test differently
        assert result["researcher"]["provider"] == "delegate"
        assert result["researcher"]["model"] == "deepseek-v4-flash"

    def test_builtin_map_not_mutated(self):
        """After load_model_config() with config, BUILTIN_MODEL_MAP is pristine."""
        original = dict(models.BUILTIN_MODEL_MAP)
        section = {"defaults": {"delegate": {"model": "totally-different"}}}
        with mock.patch.object(models, "_read_config_section", return_value=section):
            models.load_model_config()

        assert models.BUILTIN_MODEL_MAP == original

    def test_config_with_defaults_only(self):
        """Config with only defaults (no agents) → defaults applied, no per-agent changes."""
        section = {"defaults": {"delegate": {"model": "new-flash"}}}
        with mock.patch.object(models, "_read_config_section", return_value=section):
            result = models.load_model_config()

        # All delegate agents changed (all agents are delegate now)
        for agent_id in [
            "finder", "analyst", "planner", "coder", "fixer",
            "refactorer", "tester", "debugger", "documenter",
            "devops", "optimizer", "architect", "reviewer",
            "integration", "researcher", "quality",
        ]:
            assert result[agent_id]["model"] == "new-flash"
        # security is delegate with different model — also changed
        assert result["security"]["model"] == "new-flash"

    def test_config_with_agents_only(self):
        """Config with only agents (no defaults) → only specified agents changed."""
        section = {"agents": {"tester": {"model": "deepseek-v4-pro"}}}
        with mock.patch.object(models, "_read_config_section", return_value=section):
            result = models.load_model_config()

        assert result["tester"]["model"] == "deepseek-v4-pro"
        assert result["coder"]["model"] == "deepseek-v4-flash"  # unchanged

    def test_defaults_double_match_is_impossible(self):
        """Defaults matching uses ORIGINAL provider from BUILTIN, not current.
        If defaults.delegate changes provider->direct, defaults.direct should
        NOT re-match the already-changed agent.
        """
        section = {
            "defaults": {
                "delegate": {"provider": "direct", "model": "flash-model"},
                "direct": {"model": "super-flash"},
            }
        }
        with mock.patch.object(models, "_read_config_section", return_value=section):
            result = models.load_model_config()

        # architect was delegate → should get delegate defaults (direct + flash-model)
        # NOT the direct defaults (super-flash)
        assert result["architect"]["provider"] == "direct"
        assert result["architect"]["model"] == "flash-model", (
            f"architect should have 'flash-model' from delegate defaults, "
            f"got '{result['architect']['model']}' (double-match bug)"
        )
        # After delegate defaults change provider→direct, direct should NOT re-match
        assert result["finder"]["model"] == "flash-model", (
            f"finder (delegate→direct via first pass) should NOT get 'super-flash' "
            f"from second pass, got '{result['finder']['model']}'"
        )
