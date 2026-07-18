"""Unit tests for pipeline plugin core (__init__.py)."""

from __future__ import annotations

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# We import the handler functions directly (not via register)
# and set PLUGIN_DIR to a temp dir with mock prompt files
import __init__ as plugin


class TestHandleModel:
    def test_known_agent(self):
        result = json.loads(plugin.handle_model({"agent_id": "architect"}))
        assert result["provider"] == "delegate"
        assert result["model"] == "deepseek-v4-pro"

    def test_direct_agent(self):
        result = json.loads(plugin.handle_model({"agent_id": "finder"}))
        assert result["provider"] == "direct"
        assert result["model"] == "deepseek-v4-flash"

    def test_unknown_agent(self):
        result = json.loads(plugin.handle_model({"agent_id": "nonexistent"}))
        assert "error" in result

    def test_free_agent(self):
        result = json.loads(plugin.handle_model({"agent_id": "researcher"}))
        assert result["provider"] == "delegate_free"
        assert result["model"] == "openrouter/free"

    def test_reviewer_agent(self):
        result = json.loads(plugin.handle_model({"agent_id": "reviewer"}))
        assert result["provider"] == "delegate"
        assert result["model"] == "deepseek-v4-pro"


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
        assert "error" in result

    def test_prompt_path_traversal(self):
        """Agent ID with '..' should be rejected."""
        result = json.loads(plugin.handle_prompt({"agent_id": "../etc/passwd"}))
        assert "error" in result

    def test_prompt_path_traversal_subdir(self):
        """Agent ID with slash should be rejected."""
        result = json.loads(plugin.handle_prompt({"agent_id": "agents/foo"}))
        assert "error" in result

    def test_prompt_basic_build(self):
        self._write_prompt("testagent", "Request: {request}")
        result = json.loads(plugin.handle_prompt({
            "agent_id": "testagent",
            "context": {},
            "request": "hello",
        }))
        assert "prompt" in result
        assert "hello" in result["prompt"]

    def test_prompt_missing_context_placeholder(self):
        """If the template expects 'research_context' but it's missing, format handles it."""
        self._write_prompt("testagent", "{request}: {research_context}")
        result = json.loads(plugin.handle_prompt({
            "agent_id": "testagent",
            "context": {},
            "request": "test",
        }))
        assert "prompt" in result
        assert "test:" in result["prompt"]
        assert "{}" in result["prompt"]  # research_context defaults to {}

    def test_prompt_category_injection(self):
        self._write_prompt("testagent", "Category: {category}")
        result = json.loads(plugin.handle_prompt({
            "agent_id": "testagent",
            "context": {},
            "request": "",
            "category": "SECURITY_RELATED",
        }))
        assert "SECURITY_RELATED" in result["prompt"]

    def test_prompt_context_injection(self):
        self._write_prompt("testagent", "Full: {full_context}")
        result = json.loads(plugin.handle_prompt({
            "agent_id": "testagent",
            "context": {"key": "val"},
            "request": "",
        }))
        assert "val" in result["prompt"]
        assert "key" in result["prompt"]


class TestHandleConvergence:
    """Tests for pipeline_convergence handler."""

    def setup_method(self):
        import state as _state
        self.orig_path = _state.STATE_PATH
        self.tmpdir = tempfile.mkdtemp()
        _state.STATE_PATH = os.path.join(self.tmpdir, "converge_test.json")

    def teardown_method(self):
        import state as _state
        _state.STATE_PATH = self.orig_path
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _init_state(self):
        """Create an initial pipeline state."""
        plugin.pstate.save({
            "request": "test",
            "category": "FEATURE",
            "pipeline": ["finder", "coder", "reviewer"],
            "current_idx": 0,
            "completed": [],
            "context": {},
            "checkpoints": {},
            "status": "running",
        })

    def test_convergence_no_state(self):
        result = json.loads(plugin.handle_convergence({}))
        assert result["decision"] == "unknown"

    def test_convergence_converged(self):
        self._init_state()
        result = json.loads(plugin.handle_convergence({
            "findings": [{"severity": "P2", "file": "x.py", "category": "style"}],
        }))
        assert result["decision"] == "converged"

    def test_convergence_continue(self):
        self._init_state()
        result = json.loads(plugin.handle_convergence({
            "findings": [{"severity": "P0", "file": "x.py", "category": "security",
                          "description": "XSS"}],
        }))
        assert result["decision"] == "continue"
        assert result["p0_count"] == 1

    def test_convergence_stuck(self):
        """Same findings 2 rounds → stuck."""
        self._init_state()
        result1 = json.loads(plugin.handle_convergence({
            "findings": [{"severity": "P0", "file": "x.py", "category": "security",
                          "description": "XSS"}],
        }))
        assert result1["decision"] == "continue"
        result2 = json.loads(plugin.handle_convergence({
            "findings": [{"severity": "P0", "file": "x.py", "category": "security",
                          "description": "XSS"}],
        }))
        assert result2["decision"] == "stuck"

    def test_convergence_maxed_out(self):
        """3 rounds → maxed_out."""
        self._init_state()
        for _ in range(3):
            result = json.loads(plugin.handle_convergence({
                "findings": [{"severity": "P0", "file": "x.py", "category": "security",
                              "description": "XSS"}],
            }))
        assert result["decision"] == "maxed_out"


class TestHandleClassify:
    """Tests for pipeline_classify handler."""

    def test_classify_security(self):
        result = json.loads(plugin.handle_classify({
            "request": "добавь JWT аутентификацию",
        }))
        assert result["category"] == "SECURITY_RELATED"

    def test_classify_feature_default(self):
        result = json.loads(plugin.handle_classify({
            "request": "сделай импорт из CSV",
        }))
        assert result["category"] == "FEATURE"

    def test_classify_bug(self):
        result = json.loads(plugin.handle_classify({
            "request": "баг: крашится при логине",
        }))
        assert result["category"] == "BUG_UNKNOWN"
