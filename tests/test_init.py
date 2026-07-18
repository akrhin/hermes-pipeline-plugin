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
