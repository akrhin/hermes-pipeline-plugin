"""
Unit tests for pipeline plugin core (__init__.py) — Kanban-native variant.
No Kanban CLI calls — pure Python tests only.
Integration tests (scan_board, kanban CLI) live in test_kanban_integration.py.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import models as models_module

# Force deterministic tests — игнорировать локальный config.yaml
mock.patch.object(models_module, "_read_config_section", return_value=None).start()

import __init__ as plugin  # noqa: E402 — import after mock for deterministic config


class TestHandleModel:
    def test_known_agent(self):
        result = json.loads(plugin.handle_model({"agent_id": "architect"}))
        # Uses runtime MODEL_MAP (config.yaml overrides apply)
        assert result.get("provider") is not None

    def test_direct_agent(self):
        result = json.loads(plugin.handle_model({"agent_id": "finder"}))
        assert result.get("provider") is not None

    def test_unknown_agent(self):
        result = json.loads(plugin.handle_model({"agent_id": "nonexistent"}))
        assert "error" in result

    def test_free_agent(self):
        result = json.loads(plugin.handle_model({"agent_id": "researcher"}))
        assert result.get("provider") is not None

    def test_reviewer_agent(self):
        result = json.loads(plugin.handle_model({"agent_id": "reviewer"}))
        assert result.get("provider") is not None


class TestHandlePrompt:
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

    def test_prompt_unknown_agent(self):
        result = json.loads(plugin.handle_prompt({"agent_id": "unknown"}))
        # v3.2.0: unknown agents get a default prompt, not an error
        assert "prompt" in result
        assert "@unknown" in result["prompt"]
        assert "full_context" in result["prompt"]

    def test_prompt_path_traversal(self):
        """Agent ID with '..' is sanitized by basename, then gets default prompt."""
        result = json.loads(plugin.handle_prompt({"agent_id": "../etc/passwd"}))
        # os.path.basename("../etc/passwd") → "passwd" which is a valid agent name
        assert "prompt" in result
        assert "@passwd" in result["prompt"]

    def test_prompt_path_traversal_subdir(self):
        """Agent ID with slash is sanitized by basename, then gets default prompt."""
        result = json.loads(plugin.handle_prompt({"agent_id": "agents/foo"}))
        # os.path.basename("agents/foo") → "foo" which is a valid agent name
        assert "prompt" in result
        assert "@foo" in result["prompt"]

    def test_prompt_basic_build(self):
        self._write_prompt("testagent", "Request: {request}")
        result = json.loads(
            plugin.handle_prompt(
                {
                    "agent_id": "testagent",
                    "context": {},
                    "request": "hello",
                }
            )
        )
        assert "prompt" in result
        assert "hello" in result["prompt"]

    def test_prompt_missing_context_placeholder(self):
        self._write_prompt("testagent", "{request}: {research_context}")
        result = json.loads(
            plugin.handle_prompt(
                {
                    "agent_id": "testagent",
                    "context": {},
                    "request": "test",
                }
            )
        )
        assert "prompt" in result
        assert "test:" in result["prompt"]
        assert "{}" in result["prompt"]

    def test_prompt_category_injection(self):
        self._write_prompt("testagent", "Category: {category}")
        result = json.loads(
            plugin.handle_prompt(
                {
                    "agent_id": "testagent",
                    "context": {},
                    "request": "",
                    "category": "SECURITY_RELATED",
                }
            )
        )
        assert "SECURITY_RELATED" in result["prompt"]

    def test_prompt_context_injection(self):
        self._write_prompt("testagent", "Full: {full_context}")
        result = json.loads(
            plugin.handle_prompt(
                {
                    "agent_id": "testagent",
                    "context": {"key": "val"},
                    "request": "",
                }
            )
        )
        assert "val" in result["prompt"]
        assert "key" in result["prompt"]


class TestHandleConvergence:
    """Tests for pipeline_convergence handler — pure logic, no kanban CLI needed
    because state without kanban_parent_id short-circuits on_convergence()."""

    def _make_state(self):
        return {
            "request": "test",
            "category": "FEATURE",
            "pipeline": ["finder", "coder", "reviewer"],
            "current_idx": 0,
            "completed": [],
            "context": {},
            "checkpoints": {},
            "status": "running",
            "round": 0,
            "findings": [],
        }

    def test_convergence_no_state(self):
        result = json.loads(plugin.handle_convergence({"state": {}}))
        assert result["decision"] == "unknown"

    def test_convergence_converged(self):
        state = self._make_state()
        result = json.loads(
            plugin.handle_convergence(
                {
                    "state": state,
                    "findings": [{"severity": "P2", "file": "x.py", "category": "style"}],
                }
            )
        )
        assert result["decision"] == "converged"

    def test_convergence_continue(self):
        state = self._make_state()
        result = json.loads(
            plugin.handle_convergence(
                {
                    "state": state,
                    "findings": [
                        {
                            "severity": "P0",
                            "file": "x.py",
                            "category": "security",
                            "description": "XSS",
                        }
                    ],
                }
            )
        )
        assert result["decision"] == "continue"
        assert result["p0_count"] == 1

    def test_convergence_stuck(self):
        state = self._make_state()
        r1 = json.loads(
            plugin.handle_convergence(
                {
                    "state": state,
                    "findings": [
                        {
                            "severity": "P0",
                            "file": "x.py",
                            "category": "security",
                            "description": "XSS",
                        }
                    ],
                }
            )
        )
        assert r1["decision"] == "continue"
        r2 = json.loads(
            plugin.handle_convergence(
                {
                    "state": state,
                    "findings": [
                        {
                            "severity": "P0",
                            "file": "x.py",
                            "category": "security",
                            "description": "XSS",
                        }
                    ],
                }
            )
        )
        assert r2["decision"] == "stuck"

    def test_convergence_maxed_out(self):
        state = self._make_state()
        for _ in range(3):
            result = json.loads(
                plugin.handle_convergence(
                    {
                        "state": state,
                        "findings": [
                            {
                                "severity": "P0",
                                "file": "x.py",
                                "category": "security",
                                "description": "XSS",
                            }
                        ],
                    }
                )
            )
        assert result["decision"] == "maxed_out"


class TestHandleSave:
    """Basic error-path test — save with missing args returns error."""

    def test_save_missing_state(self):
        result = json.loads(plugin.handle_save({}))
        assert "error" in result


class TestHandleClassify:
    """Tests for pipeline_classify handler."""

    def test_classify_security(self):
        result = json.loads(
            plugin.handle_classify(
                {
                    "request": "добавь JWT аутентификацию",
                }
            )
        )
        assert result["primary"] == "SECURITY_RELATED"

    def test_classify_feature_default(self):
        result = json.loads(
            plugin.handle_classify(
                {
                    "request": "сделай импорт из CSV",
                }
            )
        )
        assert result["primary"] == "FEATURE"

    def test_classify_bug(self):
        result = json.loads(
            plugin.handle_classify(
                {
                    "request": "баг: крашится при логине",
                }
            )
        )
        assert result["primary"] == "BUG_UNKNOWN"


# ── pipeline_run_agent tests ───────────────────────────────────────────────


def test_run_agent_returns_delegation_package():
    """handle_run_agent returns full delegation package with expected fields."""
    from __init__ import handle_run_agent

    state = {
        "request": "добавить JWT",
        "category": "FEATURE",
        "pipeline": ["finder", "analyst", "architect"],
        "current_idx": 2,
        "completed": ["finder", "analyst"],
        "status": "running",
    }
    result = json.loads(handle_run_agent({"state": state, "agent_id": "architect"}))
    assert result["agent_id"] == "architect"
    assert result["directive"] == "delegate"
    assert result["tool_hint"] == "delegate_task"
    assert result["provider"] == "delegate"
    assert result["model"] == "deepseek-v4-pro"
    assert "prompt" in result
    assert result["call_args"] is not None
    assert result["call_args"]["prompt"] == result["prompt"]
    assert "state" in result


def test_run_agent_direct_for_flash():
    """Flash agents get directive: 'direct' and call_args: null."""
    from __init__ import handle_run_agent

    state = {
        "request": "test",
        "category": "BUG_KNOWN",
        "pipeline": ["finder", "fixer", "reviewer", "tester"],
        "current_idx": 1,
        "completed": ["finder"],
        "status": "running",
    }
    result = json.loads(handle_run_agent({"state": state, "agent_id": "fixer"}))
    assert result["directive"] == "direct"
    assert result["tool_hint"] is None
    assert result["call_args"] is None
    assert result["prompt"] is not None
    assert len(result["prompt"]) > 50


def test_run_agent_delegate_free():
    """Free-tier agents get directive: delegate_free."""
    from __init__ import handle_run_agent

    state = {
        "request": "research",
        "category": "SECURITY_RELATED",
        "pipeline": ["finder", "analyst", "researcher", "architect"],
        "current_idx": 2,
        "completed": ["finder", "analyst"],
        "status": "running",
    }
    result = json.loads(handle_run_agent({"state": state, "agent_id": "researcher"}))
    assert result["directive"] == "delegate_free"
    assert result["tool_hint"] == "delegate_task"
    assert result["call_args"] is not None
    assert result["call_args"]["provider"] == "delegate_free"


def test_run_agent_unknown_agent():
    """Unknown agent_id returns error."""
    from __init__ import handle_run_agent

    state = {"request": "x", "pipeline": ["finder"], "current_idx": 0, "status": "running"}
    result = json.loads(handle_run_agent({"state": state, "agent_id": "nonexistent"}))
    assert "error" in result
    assert "Unknown agent" in result["error"]


def test_run_agent_missing_request():
    """State missing 'request' returns error."""
    from __init__ import handle_run_agent

    state = {"pipeline": ["finder"], "current_idx": 0, "status": "running"}
    result = json.loads(handle_run_agent({"state": state, "agent_id": "finder"}))
    assert "error" in result
    assert "request" in result["error"]


def test_run_agent_missing_pipeline():
    """State missing 'pipeline' returns error."""
    from __init__ import handle_run_agent

    state = {"request": "x", "current_idx": 0, "status": "running"}
    result = json.loads(handle_run_agent({"state": state, "agent_id": "finder"}))
    assert "error" in result
    assert "pipeline" in result["error"]


def test_run_agent_context_override():
    """context parameter overrides state.context."""
    from __init__ import handle_run_agent

    state = {
        "request": "test",
        "category": "FEATURE",
        "pipeline": ["architect"],
        "current_idx": 0,
        "completed": [],
        "status": "running",
        "context": {"research": {"original": "from_state"}},
    }
    override = {"research": {"overridden": "yes"}, "planning": {}}
    result = json.loads(
        handle_run_agent({"state": state, "agent_id": "architect", "context": override})
    )
    assert result["agent_id"] == "architect"
    # prompt should contain overridden context
    assert "overridden" in result["prompt"]


def test_run_agent_path_traversal_guard():
    """Agent IDs with path traversal are sanitized."""
    from __init__ import handle_run_agent

    state = {"request": "x", "pipeline": ["finder"], "current_idx": 0, "status": "running"}
    result = json.loads(handle_run_agent({"state": state, "agent_id": "../finder"}))
    # Should resolve to "finder" after basename, not error
    assert "error" not in result
    assert result["agent_id"] == "finder"


def test_ensemble_judge_llm_returns_call_args():
    """LLM Judge mode returns judge_call_args, not a fake winner."""
    candidates = [
        {"id": "candidate_1", "temperature": 0.3, "instruction_extra": "minimal"},
        {"id": "candidate_2", "temperature": 0.5, "instruction_extra": "clean"},
        {"id": "candidate_3", "temperature": 0.7, "instruction_extra": "standard"},
        {"id": "candidate_4", "temperature": 0.9, "instruction_extra": "full"},
        {"id": "candidate_5", "temperature": 1.1, "instruction_extra": "creative"},
    ]
    from ensemble import judge_candidates
    result = judge_candidates("test request", candidates, judge_mode="llm")
    # Must NOT have fake winner_id (was bug #3)
    assert result["winner_id"] is None, f"BUG #3: got fake winner {result['winner_id']}"
    # Must have judge_call_args for orchestrator
    assert "judge_call_args" in result, "Missing judge_call_args for LLM delegation"
    assert result["judge_call_args"]["model"] == "deepseek-v4-flash"
    assert "judge_prompt" in result
    print("OK: LLM Judge returns judge_call_args, not fake winner")


def test_ensemble_judge_deterministic_picks_middle():
    """Deterministic mode picks middle candidate."""
    candidates = [{"id": f"c_{i}", "temperature": t}
                  for i, t in enumerate([0.3, 0.5, 0.7, 0.9, 1.1])]
    from ensemble import judge_candidates
    result = judge_candidates("test", candidates, judge_mode="deterministic")
    assert result["winner_id"] == "c_2", f"Expected c_2, got {result['winner_id']}"
    print("OK: Deterministic judge picks middle")


def test_ensemble_judge_empty_candidates():
    """Empty candidates returns None winner."""
    from ensemble import judge_candidates
    result = judge_candidates("test", [], judge_mode="deterministic")
    assert result["winner_id"] is None
    print("OK: Empty candidates handled")


# ── llm_judge_candidates tests ──────────────────────────────────────────────


@mock.patch("ensemble.rt.get_retro")
@mock.patch("_ctx.get_ctx")
def test_llm_judge_candidates_success(mock_get_ctx, mock_get_retro):
    """LLM Judge parses valid JSON response correctly."""
    mock_retro = mock.MagicMock()
    mock_get_retro.return_value = mock_retro
    mock_ctx = mock.MagicMock()
    mock_get_ctx.return_value = mock_ctx

    # Mock .llm.complete() to return a PluginLlmCompleteResult-like object
    mock_result = mock.MagicMock()
    mock_result.text = '{"winner_id": "candidate_3", "rationale": "Best quality", "scores": []}'
    mock_result.usage.input_tokens = 150
    mock_result.usage.output_tokens = 50
    mock_ctx.llm.complete.return_value = mock_result

    from ensemble import llm_judge_candidates

    candidates = [
        {"id": "candidate_1", "temperature": 0.3},
        {"id": "candidate_2", "temperature": 0.5},
        {"id": "candidate_3", "temperature": 0.7},
    ]
    result = llm_judge_candidates("test request", candidates)

    assert result["winner_id"] == "candidate_3"
    assert result["rationale"] == "Best quality"
    assert result["mode"] == "llm"
    assert result["usage"]["input_tokens"] == 150
    assert result["usage"]["output_tokens"] == 50
    mock_ctx.llm.complete.assert_called_once()
    mock_retro.ensemble_judge.assert_called_once_with(
        winner="candidate_3", mode="llm", rationale="Best quality"
    )
    print("OK: llm_judge_candidates parses valid JSON")


@mock.patch("ensemble.rt.get_retro")
@mock.patch("_ctx.get_ctx")
def test_llm_judge_candidates_json_fence(mock_get_ctx, mock_get_retro):
    """LLM Judge handles JSON wrapped in ```json fences."""
    mock_retro = mock.MagicMock()
    mock_get_retro.return_value = mock_retro
    mock_ctx = mock.MagicMock()
    mock_get_ctx.return_value = mock_ctx

    mock_result = mock.MagicMock()
    mock_result.text = "```json\n{\"winner_id\": \"candidate_1\"}\n```"
    mock_result.usage.input_tokens = 100
    mock_result.usage.output_tokens = 30
    mock_ctx.llm.complete.return_value = mock_result

    from ensemble import llm_judge_candidates

    candidates = [
        {"id": "candidate_1", "temperature": 0.3},
        {"id": "candidate_2", "temperature": 0.5},
    ]
    result = llm_judge_candidates("test", candidates)
    assert result["winner_id"] == "candidate_1"
    assert result["mode"] == "llm"
    print("OK: llm_judge_candidates handles fenced JSON")


@mock.patch("ensemble.rt.get_retro")
@mock.patch("_ctx.get_ctx")
def test_llm_judge_candidates_no_ctx(mock_get_ctx, mock_get_retro):
    """When ctx is None, falls back to deterministic."""
    mock_get_ctx.return_value = None

    from ensemble import llm_judge_candidates

    candidates = [
        {"id": "c_0", "temperature": 0.3},
        {"id": "c_1", "temperature": 0.5},
        {"id": "c_2", "temperature": 0.7},
        {"id": "c_3", "temperature": 0.9},
        {"id": "c_4", "temperature": 1.1},
    ]
    result = llm_judge_candidates("test", candidates)
    assert result["winner_id"] == "c_2"  # deterministic middle
    assert result["mode"] == "deterministic"
    print("OK: llm_judge_candidates falls back to deterministic when no ctx")


@mock.patch("ensemble.rt.get_retro")
@mock.patch("_ctx.get_ctx")
def test_llm_judge_candidates_llm_error(mock_get_ctx, mock_get_retro):
    """When ctx.llm.complete() raises, falls back to deterministic."""
    mock_retro = mock.MagicMock()
    mock_get_retro.return_value = mock_retro
    mock_ctx = mock.MagicMock()
    mock_get_ctx.return_value = mock_ctx
    mock_ctx.llm.complete.side_effect = RuntimeError("LLM unavailable")

    from ensemble import llm_judge_candidates

    candidates = [
        {"id": "c_0", "temperature": 0.3},
        {"id": "c_1", "temperature": 0.5},
        {"id": "c_2", "temperature": 0.7},
    ]
    result = llm_judge_candidates("test", candidates)
    assert result["winner_id"] == "c_1"  # deterministic middle
    assert result["mode"] == "deterministic"
    print("OK: llm_judge_candidates falls back on LLM error")
