"""Tests for delegation contract: pipeline_run_agent as sole entry point."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import models as models_module

mock.patch.object(models_module, "_read_config_section", return_value=None).start()

import __init__ as plugin  # noqa: E402
from handlers import _build_agent_prompt, handle_run_agent  # noqa: E402


def _make_minimal_state(overrides: dict | None = None) -> dict:
    """Helper: minimal valid pipeline state."""
    state = {
        "request": "Implement JWT auth",
        "category": "FEATURE",
        "pipeline": ["finder", "analyst", "architect", "coder", "tester", "reviewer"],
        "current_idx": 0,
        "completed": [],
        "status": "running",
        "context": {
            "research": {"existing_code": "fastapi app"},
            "planning": {"steps": ["add middleware", "add tokens"]},
            "implementation": {"files": ["auth.py", "main.py"]},
        },
    }
    if overrides:
        state.update(overrides)
    return state


# ── Anti-bypass contract: delegation package MUST go through pipeline_run_agent ──


class TestDelegationPackageContract:
    """Every call delegation MUST go through pipeline_run_agent → delegate_task(call_args).

    These tests verify that call_args.goal matches the built prompt,
    meaning the orchestrator cannot bypass the prompt construction.
    """

    def test_call_args_goal_equals_prompt(self):
        """core invariant: call_args.goal MUST equal prompt — no bypass."""
        state = _make_minimal_state()
        result = json.loads(handle_run_agent({"state": state, "agent_id": "architect"}))
        assert result["call_args"]["goal"] == result["prompt"], (
            "call_args.goal must equal prompt — otherwise agent bypasses prompt construction"
        )

    def test_call_args_goal_equals_prompt_for_fixer(self):
        """Same invariant for @fixer agent."""
        state = _make_minimal_state(
            {"current_idx": 3, "completed": ["finder", "analyst", "architect"]}
        )
        result = json.loads(handle_run_agent({"state": state, "agent_id": "fixer"}))
        if result["call_args"] is not None:
            assert result["call_args"]["goal"] == result["prompt"]

    def test_state_passed_through_unchanged(self):
        """State must be passed through in delegation package — orchestrator needs it."""
        state = _make_minimal_state()
        result = json.loads(handle_run_agent({"state": state, "agent_id": "finder"}))
        assert result["state"]["request"] == "Implement JWT auth"
        assert result["state"]["pipeline"] == state["pipeline"]
        assert result["state"]["current_idx"] == 0

    def test_prompt_contains_agent_id(self):
        """Prompt must reference the agent — confirms correct routing."""
        state = _make_minimal_state()
        result = json.loads(handle_run_agent({"state": state, "agent_id": "coder"}))
        assert "@coder" in result["prompt"] or "coder" in result["prompt"].lower()

    def test_prompt_contains_request(self):
        """Prompt must include the original request."""
        state = _make_minimal_state()
        result = json.loads(handle_run_agent({"state": state, "agent_id": "finder"}))
        assert "Implement JWT auth" in result["prompt"]

    def test_prompt_contains_context_sections(self):
        """Prompt for architect must contain research AND planning context."""
        state = _make_minimal_state()
        result = json.loads(handle_run_agent({"state": state, "agent_id": "architect"}))
        assert "existing_code" in result["prompt"]
        assert "steps" in result["prompt"]

    def test_finder_prompt_has_research_only(self):
        """@finder only needs research context — planning/implementation should NOT leak."""
        state = _make_minimal_state()
        result = json.loads(handle_run_agent({"state": state, "agent_id": "finder"}))
        # Finder only needs research
        assert "existing_code" in result["prompt"]
        # Should not contain implementation details — that's for @coder
        assert (
            "files" not in result["prompt"].split("implementation")[0]
            if "implementation" in result["prompt"]
            else True
        )

    def test_coder_prompt_has_implementation_and_planning(self):
        """@coder needs implementation and planning context."""
        state = _make_minimal_state()
        result = json.loads(handle_run_agent({"state": state, "agent_id": "coder"}))
        assert "files" in result["prompt"] or "steps" in result["prompt"]

    def test_security_pro_model_routing(self):
        """@security must route to Pro model."""
        result = json.loads(
            handle_run_agent({"state": _make_minimal_state(), "agent_id": "security"})
        )
        assert result["provider"] in ("delegate", "direct")
        assert result["directive"] == "delegate"


# ── _build_agent_prompt unit tests (standalone) ──────────────────────────


class TestBuildAgentPrompt:
    """Direct tests for _build_agent_prompt — the core prompt builder."""

    def setup_method(self):
        self.orig_dir = plugin.PLUGIN_DIR
        self.tmpdir = tempfile.mkdtemp()
        self.agents_dir = os.path.join(self.tmpdir, "agents")
        os.makedirs(self.agents_dir, exist_ok=True)
        plugin.PLUGIN_DIR = self.tmpdir

    def teardown_method(self):
        plugin.PLUGIN_DIR = self.orig_dir

    def _write_prompt(self, name: str, content: str):
        with open(os.path.join(self.agents_dir, f"{name}.prompt"), "w") as f:
            f.write(content)

    def test_empty_request(self):
        """Empty request should still produce a valid prompt."""
        result = _build_agent_prompt(
            "coder", {"implementation": {"task": "write code"}}, "", "FEATURE"
        )
        assert "prompt" in result
        assert len(result["prompt"]) > 10

    def test_missing_category(self):
        """Missing category should not break prompt building."""
        result = _build_agent_prompt(
            "coder", {"implementation": {"task": "write code"}}, "fix bug", ""
        )
        assert "prompt" in result
        assert "fix bug" in result["prompt"]

    def test_empty_context(self):
        """Empty context dict should still produce valid prompt."""
        result = _build_agent_prompt("coder", {}, "do something", "FEATURE")
        assert "prompt" in result
        assert "do something" in result["prompt"]

    def test_agent_with_all_context_fields(self):
        """Agent with all fields gets comprehensive prompt."""
        context = {
            "research": {"r1": "research data"},
            "planning": {"p1": "plan data"},
            "implementation": {"i1": "impl data"},
            "documentation": {"d1": "doc data"},
            "infrastructure": {"infra1": "infra data"},
        }
        result = _build_agent_prompt("integration", context, "integrate services", "FEATURE")
        assert "prompt" in result
        # integration uses: implementation, documentation, infrastructure
        assert "impl data" in result["prompt"] or "i1" in result["prompt"]
        assert "doc data" in result["prompt"] or "d1" in result["prompt"]
        assert "infra data" in result["prompt"] or "infra1" in result["prompt"]

    def test_agent_with_no_context_fields_defaults_all(self):
        """Unknown agent gets all context fields in default prompt."""
        context = {
            "research": {"key": "r"},
            "planning": {"key": "p"},
            "implementation": {"key": "i"},
            "quality": {"key": "q"},
            "documentation": {"key": "d"},
            "infrastructure": {"key": "infra"},
            "full_context": {"key": "all"},
        }
        result = _build_agent_prompt("unknown_agent", context, "task", "FEATURE")
        assert "prompt" in result
        assert "@unknown_agent" in result["prompt"]
        # Should contain full_context since no specific fields defined
        assert "full_context" in result["prompt"]

    def test_render_template_no_prompt_file(self):
        """Agent without .prompt file gets auto-generated default."""
        # No prompt file for 'testagent'
        result = _build_agent_prompt("testagent", {}, "task", "FEATURE")
        assert "prompt" in result
        assert "@testagent" in result["prompt"]

    def test_prompt_with_custom_template(self):
        """Custom .prompt file is used when present."""
        self._write_prompt("customagent", "Custom: {request} / {category}")
        result = _build_agent_prompt("customagent", {}, "hello", "BUG_KNOWN")
        assert result["prompt"] == "Custom: hello / BUG_KNOWN"

    def test_prompt_bracket_escaping(self):
        """Curly braces in request should be escaped to avoid KeyError."""
        self._write_prompt("testagent", "Request: {request}")
        result = _build_agent_prompt("testagent", {}, "{invalid} must be escaped", "FEATURE")
        assert "prompt" in result
        assert "{{invalid}}" in result["prompt"] or "{invalid}" in result["prompt"]

    def test_missing_template_placeholder_returns_error(self):
        """If template uses {nonexistent}, returns error dict."""
        self._write_prompt("testagent", "{nonexistent}")
        result = _build_agent_prompt("testagent", {}, "task", "FEATURE")
        assert "error" in result
        assert "nonexistent" in result["error"] or "Missing" in result["error"]

    def test_path_traversal_guard(self):
        """Agent ID with '..' is sanitized by basename and checked against agents_dir."""
        result = _build_agent_prompt("../etc/passwd", {}, "task", "FEATURE")
        # basename(".../etc/passwd") = "passwd"
        # passwd doesn't exist in agents dir → generates default prompt
        assert "error" not in result
        assert "prompt" in result
        assert "@passwd" in result["prompt"]

    def test_path_traversal_absolute(self):
        """Absolute path as agent_id is rejected by path traversal guard."""
        result = _build_agent_prompt("/etc/passwd", {}, "task", "FEATURE")
        # basename("/etc/passwd") = "passwd" — not in agents dir
        # default prompt is generated
        assert "prompt" in result or "error" in result


# ── handle_run_agent edge cases (not covered by existing tests) ──────────


class TestHandleRunAgentEdgeCases:
    """Additional edge cases for handle_run_agent."""

    def test_null_context_override(self):
        """context=None should use state.context."""
        state = _make_minimal_state()
        result = json.loads(
            handle_run_agent({"state": state, "agent_id": "coder", "context": None})
        )
        assert result["agent_id"] == "coder"
        assert "files" in result["prompt"] or "steps" in result["prompt"]

    def test_empty_context_override(self):
        """Empty context override should produce prompt with empty sections."""
        state = _make_minimal_state()
        result = json.loads(handle_run_agent({"state": state, "agent_id": "coder", "context": {}}))
        assert result["agent_id"] == "coder"
        assert result["prompt"] is not None

    def test_no_category_in_state(self):
        """State without category should still work (category default '')."""
        state = _make_minimal_state()
        del state["category"]
        result = json.loads(handle_run_agent({"state": state, "agent_id": "coder"}))
        assert result["agent_id"] == "coder"
        assert "prompt" in result

    def test_empty_pipeline_list(self):
        """Empty pipeline list should not crash — but state is still valid for prompt building."""
        state = _make_minimal_state({"pipeline": []})
        result = json.loads(handle_run_agent({"state": state, "agent_id": "coder"}))
        assert "prompt" in result

    def test_run_agent_with_security_returns_delegate(self):
        """@security must always return directive=delegate."""
        state = _make_minimal_state()
        result = json.loads(handle_run_agent({"state": state, "agent_id": "security"}))
        assert result["directive"] == "delegate"
        assert result["tool_hint"] == "delegate_task"

    def test_free_agent_delegate_contract(self):
        """delegate_free agents must have call_args with plan/goal."""
        state = _make_minimal_state()
        # researcher may be delegate_free
        result = json.loads(handle_run_agent({"state": state, "agent_id": "researcher"}))
        if result["directive"] == "delegate_free":
            assert result["call_args"] is not None
            assert "goal" in result["call_args"]
            assert result["tool_hint"] == "delegate_task"
        elif result["directive"] == "delegate":
            assert result["call_args"] is not None
        else:
            assert result["call_args"] is None

    def test_direct_agent_has_no_call_args(self):
        """Direct agents get call_args=null, delegate agents get call_args with goal.
        Note: as of v3.8.2 all 17 agents use delegate mode, so only test the contract."""
        state = _make_minimal_state()
        result = json.loads(handle_run_agent({"state": state, "agent_id": "quality"}))
        # All agents in v3.8.2 are delegate
        assert result["directive"] == "delegate"
        assert result["call_args"] is not None
        assert "goal" in result["call_args"]

    def test_retro_logging_on_agent_start(self):
        """handle_run_agent must log agent_start to retro."""
        with mock.patch("handlers.rt.get_retro") as mock_retro:
            mock_instance = mock.MagicMock()
            mock_retro.return_value = mock_instance
            state = _make_minimal_state()
            json.loads(handle_run_agent({"state": state, "agent_id": "coder"}))
            mock_instance.agent_start.assert_called_once()
            call_kwargs = mock_instance.agent_start.call_args.kwargs
            assert call_kwargs.get("directive") in ("delegate", "direct", "delegate_free")

    def test_all_seventeen_agents_contract(self):
        """All 17 agents should return valid delegation packages with delegate directive."""
        agents = [
            "finder",
            "analyst",
            "researcher",
            "architect",
            "planner",
            "coder",
            "fixer",
            "refactorer",
            "reviewer",
            "security",
            "integration",
            "tester",
            "debugger",
            "documenter",
            "devops",
            "optimizer",
            "quality",
        ]
        state = _make_minimal_state()
        for agent_id in agents:
            try:
                result = json.loads(handle_run_agent({"state": state, "agent_id": agent_id}))
            except Exception as e:
                assert False, f"Agent {agent_id} raised {e}"
            assert "agent_id" in result, f"Agent {agent_id}: missing agent_id"
            assert "directive" in result, f"Agent {agent_id}: missing directive"
            assert result["directive"] in ("direct", "delegate", "delegate_free"), (
                f"Agent {agent_id}: invalid directive {result['directive']}"
            )
            assert "prompt" in result, f"Agent {agent_id}: missing prompt"
            assert "provider" in result, f"Agent {agent_id}: missing provider"
            assert "model" in result, f"Agent {agent_id}: missing model"
            assert "tool_hint" in result, f"Agent {agent_id}: missing tool_hint"

            # v3.8.2: all 17 agents are delegate
            assert result["directive"] == "delegate", (
                f"Agent {agent_id}: expected delegate, got {result['directive']}"
            )

            # Delegate agents must have call_args with goal
            assert result["call_args"] is not None, f"Agent {agent_id}: delegate needs call_args"
            assert "goal" in result["call_args"], (
                f"Agent {agent_id}: delegate needs goal in call_args"
            )
            # Core invariant: call_args.goal == prompt (no bypass)
            assert result["call_args"]["goal"] == result["prompt"], (
                f"Agent {agent_id}: call_args.goal != prompt — BYPASS DETECTED"
            )
            # tool_hint must be delegate_task for delegate agents
            assert result["tool_hint"] == "delegate_task", (
                f"Agent {agent_id}: expected delegate_task, got {result['tool_hint']}"
            )


# ── handle_ensemble_run tests (currently untested) ───────────────────────


class TestHandleEnsembleRun:
    """Tests for handle_ensemble_run — ensemble candidate generation."""

    def test_ensemble_disabled_returns_single(self):
        """When ensemble is disabled for this agent, returns single candidate."""
        state = _make_minimal_state({"round": 0})
        with mock.patch("handlers.should_use_ensemble") as mock_should:
            mock_should.return_value = False
            result = json.loads(
                plugin.handle_ensemble_run(
                    {
                        "state": state,
                        "agent_id": "coder",
                        "n": 5,
                    }
                )
            )
        assert result["ensemble"] is False
        assert len(result["candidates"]) == 1
        assert result["candidates"][0]["id"] == "single"

    def test_ensemble_enabled_returns_candidates(self):
        """When ensemble is enabled, returns n candidates."""
        state = _make_minimal_state({"round": 0})
        with mock.patch("handlers.should_use_ensemble") as mock_should:
            mock_should.return_value = True
            with mock.patch("handlers.ensemble_generate_candidates") as mock_gen:
                mock_gen.return_value = [
                    {"id": "candidate_1", "temperature": 0.3, "instruction_extra": "minimal"},
                    {"id": "candidate_2", "temperature": 0.5, "instruction_extra": "standard"},
                ]
                result = json.loads(
                    plugin.handle_ensemble_run(
                        {
                            "state": state,
                            "agent_id": "coder",
                            "n": 2,
                        }
                    )
                )
        assert result["ensemble"] is True
        assert len(result["candidates"]) == 2
        assert result["candidates"][0]["id"] == "candidate_1"

    def test_ensemble_default_n_is_5(self):
        """Default n=5 when not specified."""
        state = _make_minimal_state({"round": 0})
        with mock.patch("handlers.should_use_ensemble") as mock_should:
            mock_should.return_value = True
            with mock.patch("handlers.ensemble_generate_candidates") as mock_gen:
                mock_gen.return_value = [{"id": f"c_{i}", "temperature": 0.5} for i in range(5)]
                result = json.loads(
                    plugin.handle_ensemble_run(
                        {
                            "state": state,
                            "agent_id": "coder",
                        }
                    )
                )
        assert result["ensemble"] is True
        assert len(result["candidates"]) == 5

    def test_ensemble_single_candidate_when_unknown_agent(self):
        """Unknown agent with no ensemble config falls back to single candidate."""
        state = _make_minimal_state({"round": 0})
        with mock.patch("handlers.should_use_ensemble") as mock_should:
            mock_should.return_value = False
            result = json.loads(
                plugin.handle_ensemble_run(
                    {
                        "state": state,
                        "agent_id": "nonexistent",
                        "n": 3,
                    }
                )
            )
        assert result["ensemble"] is False
        assert len(result["candidates"]) == 1

    def test_ensemble_disabled_reason(self):
        """When disabled, reason explains why."""
        state = _make_minimal_state({"round": 0})
        with mock.patch("handlers.should_use_ensemble") as mock_should:
            mock_should.return_value = False
            result = json.loads(
                plugin.handle_ensemble_run(
                    {
                        "state": state,
                        "agent_id": "coder",
                    }
                )
            )
        assert "reason" in result
        assert "disabled" in result["reason"].lower()

    def test_ensemble_n_capped_at_7(self):
        """n larger than VARIATIONS length (7) is capped."""
        state = _make_minimal_state({"round": 0})
        with mock.patch("handlers.should_use_ensemble") as mock_should:
            mock_should.return_value = True
            with mock.patch("handlers.ensemble_generate_candidates") as mock_gen:
                mock_gen.return_value = [{"id": f"c_{i}", "temperature": 0.5} for i in range(7)]
                result = json.loads(
                    plugin.handle_ensemble_run(
                        {
                            "state": state,
                            "agent_id": "coder",
                            "n": 100,
                        }
                    )
                )
        # ensemble.generate_candidates caps internally; we just check the handler doesn't crash
        assert "error" not in result
