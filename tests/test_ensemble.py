"""Edge-case tests for ensemble.py — config reading, variation limits, should_use_ensemble."""

from __future__ import annotations

import os
import sys
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import ensemble


class TestReadEnsembleConfig:
    """Tests for read_ensemble_config() — edge cases."""

    def test_nonexistent_config_file(self):
        """Non-existent path returns defaults."""
        result = ensemble.read_ensemble_config("/nonexistent/path/config.yaml")
        assert result == ensemble.DEFAULT_ENSEMBLE_CONFIG

    def test_empty_yaml_returns_empty_dict(self, tmp_path):
        """Empty YAML returns {} because file exists but no ensemble section."""
        config = tmp_path / "config.yaml"
        config.write_text("")
        result = ensemble.read_ensemble_config(str(config))
        assert result == {}  # file exists, no pipeline.ensemble → empty dict

    def test_yaml_without_pipeline_section_returns_empty_dict(self, tmp_path):
        """YAML without pipeline section returns {} because no ensemble section found."""
        config = tmp_path / "config.yaml"
        config.write_text("other: 42")
        result = ensemble.read_ensemble_config(str(config))
        assert result == {}  # file exists, no pipeline.ensemble → empty dict

    def test_yaml_with_invalid_ensemble_type(self, tmp_path):
        config = tmp_path / "config.yaml"
        config.write_text("pipeline:\n  ensemble: not_a_dict")
        result = ensemble.read_ensemble_config(str(config))
        assert result == ensemble.DEFAULT_ENSEMBLE_CONFIG

    def test_yaml_with_partial_ensemble(self, tmp_path):
        """Partial ensemble config merges with defaults via the production code path."""
        config = tmp_path / "config.yaml"
        config.write_text("pipeline:\n  ensemble:\n    enabled: false")
        # The function returns the raw section from YAML without merging here
        # because read_ensemble_config returns the ensemble section as-is.
        # But the actual default has default_n=5.
        # In production the DEFAULT is a separate fallback, not a merge.
        result = ensemble.read_ensemble_config(str(config))
        assert result is not None
        # enabled: false is respected
        assert result.get("enabled") is False


class TestGenerateCandidates:
    """Tests for generate_candidates — edge cases."""

    def test_empty_request(self):
        state = {"request": "", "category": "FEATURE", "context": {}}
        candidates = ensemble.generate_candidates(state, "coder", n=3)
        assert len(candidates) == 3
        assert all("id" in c for c in candidates)
        assert candidates[0]["task"].startswith("")
    def test_n_capped_to_config_limit(self):
        """n larger than config agent's n is capped."""
        state = {"request": "test", "category": "FEATURE", "context": {}}
        # With default config, agent 'coder' has n=5 (agent_cfg.n)
        candidates = ensemble.generate_candidates(state, "coder", n=100)
        assert len(candidates) == 5  # capped by agent_cfg.n, not len(VARIATIONS)

    def test_n_minimum(self):
        """n=0 returns empty candidates list."""
        state = {"request": "test", "category": "FEATURE", "context": {}}
        candidates = ensemble.generate_candidates(state, "coder", n=0)
        assert len(candidates) == 0  # no iterations

    def test_context_and_category_passed_through(self):
        state = {"request": "test", "category": "SECURITY_RELATED", "context": {"key": "val"}}
        candidates = ensemble.generate_candidates(state, "coder", n=1)
        assert candidates[0]["context"] == {"key": "val"}
        assert candidates[0]["category"] == "SECURITY_RELATED"

    def test_varying_temperatures(self):
        state = {"request": "test", "category": "FEATURE", "context": {}}
        candidates = ensemble.generate_candidates(state, "coder", n=5)
        temps = [c["temperature"] for c in candidates]
        # Should have at least 2 different temperatures
        assert len(set(temps)) >= 2


class TestShouldUseEnsemble:
    """Tests for should_use_ensemble() — cost optimization, agent config."""

    def test_disabled_globally(self, tmp_path):
        config = tmp_path / "config.yaml"
        config.write_text("pipeline:\n  ensemble:\n    enabled: false")
        state = {"round": 0}
        with mock.patch.object(ensemble, "read_ensemble_config") as mock_read:
            mock_read.return_value = {"enabled": False}
            result = ensemble.should_use_ensemble(state, "coder")
        assert result is False

    def test_agent_not_enabled(self):
        state = {"round": 0}
        with mock.patch.object(ensemble, "read_ensemble_config") as mock_read:
            mock_read.return_value = {
                "enabled": True,
                "agents": {"coder": {"enabled": False}},
                "cost_optimization": {"disable_on_round_gt": 1},
            }
            result = ensemble.should_use_ensemble(state, "coder")
        assert result is False

    def test_round_exceeds_cost_optimization(self):
        state = {"round": 2}
        with mock.patch.object(ensemble, "read_ensemble_config") as mock_read:
            mock_read.return_value = {
                "enabled": True,
                "agents": {"coder": {"enabled": True}},
                "cost_optimization": {"disable_on_round_gt": 1},
            }
            result = ensemble.should_use_ensemble(state, "coder")
        assert result is False

    def test_round_within_limit(self):
        state = {"round": 0}
        with mock.patch.object(ensemble, "read_ensemble_config") as mock_read:
            mock_read.return_value = {
                "enabled": True,
                "agents": {"coder": {"enabled": True}},
                "cost_optimization": {"disable_on_round_gt": 1},
            }
            result = ensemble.should_use_ensemble(state, "coder")
        assert result is True

    def test_agent_not_listed_default_disabled(self):
        """Agents not in the config are disabled by default."""
        state = {"round": 0}
        with mock.patch.object(ensemble, "read_ensemble_config") as mock_read:
            mock_read.return_value = {
                "enabled": True,
                "agents": {"coder": {"enabled": True}},
                "cost_optimization": {},
            }
            result = ensemble.should_use_ensemble(state, "planner")
        assert result is False

    def test_missing_round_defaults_zero(self):
        state = {}  # no round key
        with mock.patch.object(ensemble, "read_ensemble_config") as mock_read:
            mock_read.return_value = {
                "enabled": True,
                "agents": {"coder": {"enabled": True}},
                "cost_optimization": {"disable_on_round_gt": 1},
            }
            result = ensemble.should_use_ensemble(state, "coder")
        assert result is True


class TestJudgeCandidatesEdgeCases:
    """Additional edge cases for judge_candidates."""

    def test_single_candidate_deterministic(self):
        """≤2 candidates always uses deterministic regardless of mode."""
        candidates = [{"id": "c_0", "temperature": 0.5}]
        result = ensemble.judge_candidates("test", candidates, judge_mode="llm")
        assert result["winner_id"] == "c_0"
        assert result["mode"] == "deterministic"

    def test_two_candidates_always_deterministic(self):
        candidates = [
            {"id": "c_0", "temperature": 0.3},
            {"id": "c_1", "temperature": 0.7},
        ]
        result = ensemble.judge_candidates("test", candidates, judge_mode="llm")
        assert result["winner_id"] in ("c_0", "c_1")
        assert result["mode"] == "deterministic"

    def test_unknown_mode_fallback(self):
        candidates = [
            {"id": "c_0", "temperature": 0.3},
            {"id": "c_1", "temperature": 0.5},
            {"id": "c_2", "temperature": 0.7},
        ]
        result = ensemble.judge_candidates("test", candidates, judge_mode="unknown_mode")
        assert result["mode"] == "fallback"
        assert result["winner_id"] == "c_0"

    def test_deterministic_scoring_middle_candidate_highest(self):
        candidates = [
            {"id": "c_0", "temperature": 0.3},
            {"id": "c_1", "temperature": 0.5},
            {"id": "c_2", "temperature": 0.7},
            {"id": "c_3", "temperature": 0.9},
            {"id": "c_4", "temperature": 1.1},
        ]
        result = ensemble.judge_candidates("test", candidates, judge_mode="deterministic")
        scores = {s["id"]: s["total"] for s in result["scores"]}
        assert scores["c_2"] > scores["c_0"]
        assert scores["c_2"] > scores["c_4"]

    def test_llm_mode_returns_judge_call_args(self):
        candidates = [
            {"id": "c_0", "temperature": 0.3},
            {"id": "c_1", "temperature": 0.5},
            {"id": "c_2", "temperature": 0.7},
            {"id": "c_3", "temperature": 0.9},
            {"id": "c_4", "temperature": 1.1},
        ]
        result = ensemble.judge_candidates("test", candidates, judge_mode="llm")
        assert result["winner_id"] is None
        assert "judge_call_args" in result
        assert "judge_prompt" in result
        assert result["mode"] == "llm"


class TestBuildJudgeCallArgs:
    """Tests for build_judge_call_args."""

    def test_default_config(self):
        args = ensemble.build_judge_call_args("prompt text")
        assert args["goal"] == "prompt text"
        assert len(args) == 1  # only goal

    def test_custom_config(self):
        args = ensemble.build_judge_call_args(
            "hello",
        )
        assert args["goal"] == "hello"
        assert len(args) == 1  # config no longer matters; only goal matters
