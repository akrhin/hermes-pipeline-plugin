"""Edge-case tests for kanban.py — resume, parse helpers, idempotency keys, SQLite pool."""

from __future__ import annotations

import os
import sys
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import kanban as kb


class TestExtractTarget:
    """Tests for _extract_target — request parsing."""

    def test_empty_request(self):
        assert kb._extract_target("") == "проект"

    def test_none_request(self):
        assert kb._extract_target(None) == "проект"

    def test_known_project_name(self):
        assert kb._extract_target("fix bug in hermes-pipeline-plugin") == "hermes-pipeline-plugin"

    def test_known_file_name(self):
        assert kb._extract_target("refactor kanban.py") == "kanban.py"

    def test_known_config_file(self):
        assert kb._extract_target("update config.yaml") == "config.yaml"

    def test_preposition_target(self):
        assert kb._extract_target("добавить в auth.py") == "auth.py"

    def test_first_word_fallback(self):
        result = kb._extract_target("оптимизация базы данных")
        assert result == "оптимизация"

    def test_case_insensitive_known(self):
        assert kb._extract_target("Fix Kanban.py") == "kanban.py"
        assert kb._extract_target("update Config.Yaml") == "config.yaml"

    def test_request_without_known_target(self):
        result = kb._extract_target("напиши тесты")
        assert len(result) > 0
        assert result != "проект"  # "напиши" should match first 3+ char word


class TestParentTaskId:
    """Tests for parent_task_id — deterministic idempotency keys."""

    def test_deterministic(self):
        id1 = kb.parent_task_id(["finder", "coder"], "test request")
        id2 = kb.parent_task_id(["finder", "coder"], "test request")
        assert id1 == id2
        assert id1.startswith("pipe:")

    def test_differs_by_pipeline(self):
        id1 = kb.parent_task_id(["finder"], "test")
        id2 = kb.parent_task_id(["coder"], "test")
        assert id1 != id2

    def test_differs_by_request(self):
        id1 = kb.parent_task_id(["finder"], "request A")
        id2 = kb.parent_task_id(["finder"], "request B")
        assert id1 != id2

    def test_request_truncated_to_40_chars(self):
        long_req = "a" * 100
        id1 = kb.parent_task_id(["finder"], long_req)
        id2 = kb.parent_task_id(["finder"], "a" * 40)
        assert id1 == id2  # truncated to same


class TestChildId:
    """Tests for child_id."""

    def test_deterministic(self):
        c1 = kb.child_id("pipe:abc", "coder")
        c2 = kb.child_id("pipe:abc", "coder")
        assert c1 == c2

    def test_differs_by_agent(self):
        c1 = kb.child_id("pipe:abc", "coder")
        c2 = kb.child_id("pipe:abc", "tester")
        assert c1 != c2

    def test_differs_by_round(self):
        c1 = kb.child_id("pipe:abc", "coder", round_num=0)
        c2 = kb.child_id("pipe:abc", "coder", round_num=1)
        assert c1 != c2

    def test_contains_round_in_name(self):
        cid = kb.child_id("pipe:abc", "coder", round_num=2)
        assert ":r2" in cid


class TestParseCategories:
    """Tests for _parse_categories."""

    def test_single_category(self):
        cats, primary = kb._parse_categories("Категория: FEATURE\n\nSome request")
        assert cats == ["FEATURE"]
        assert primary == "FEATURE"

    def test_multi_category_line(self):
        cats, primary = kb._parse_categories(
            "Категории: BUG_KNOWN, SECURITY_RELATED\n\nRequest"
        )
        assert cats == ["BUG_KNOWN", "SECURITY_RELATED"]
        assert primary == "BUG_KNOWN"

    def test_missing_category(self):
        cats, primary = kb._parse_categories("No category here")
        assert cats == []
        assert primary == ""

    def test_empty_body(self):
        cats, primary = kb._parse_categories("")
        assert cats == []
        assert primary == ""


class TestRestoreFindingsFromBody:
    """Tests for _restore_findings_from_body."""

    def test_no_findings_in_body(self):
        result = kb._restore_findings_from_body("Just a normal body")
        assert result == []

    def test_empty_body(self):
        result = kb._restore_findings_from_body("")
        assert result == []

    def test_findings_with_json(self):
        body = (
            "Категория: FEATURE\n"
            "Findings:[{\"severity\": \"P0\", \"file\": \"x.py\", \"category\": \"sec\"}]\n"
            "Other content"
        )
        result = kb._restore_findings_from_body(body)
        assert len(result) == 1
        assert result[0]["severity"] == "P0"

    def test_findings_hash_prefix(self):
        body = (
            "#Findings:[{\"severity\": \"P1\", \"file\": \"y.py\", \"category\": \"style\"}]\n"
        )
        result = kb._restore_findings_from_body(body)
        assert len(result) == 1
        assert result[0]["severity"] == "P1"

    def test_invalid_json_returns_empty(self):
        body = "Findings:not valid json"
        result = kb._restore_findings_from_body(body)
        assert result == []

    def test_malformed_json_returns_empty(self):
        body = "Findings:{bad json}"
        result = kb._restore_findings_from_body(body)
        assert result == []


class TestParsePipelineOrder:
    """Tests for _parse_pipeline_order."""

    def test_from_agents_line(self):
        body = "Агенты: @finder → @coder → @tester"
        result = kb._parse_pipeline_order(body, [])
        assert result == ["finder", "coder", "tester"]

    def test_agents_with_alternate_colon(self):
        body = "Агенты : @finder → @coder"
        result = kb._parse_pipeline_order(body, [])
        assert result == ["finder", "coder"]

    def test_fallback_from_children(self):
        body = "No agents line here"
        children = [
            {"title": "@finder: разведка проект"},
            {"title": "@coder: разработка проект"},
        ]
        result = kb._parse_pipeline_order(body, children)
        assert result == ["finder", "coder"]

    def test_empty_body_no_children(self):
        result = kb._parse_pipeline_order("", [])
        assert result == []


class TestBuildStateFromBoard:
    """Tests for _build_state_from_board — state reconstruction."""

    def test_happy_path(self):
        parent = {
            "id": "pipe:abc123",
            "title": "🔷  Пайплайн: test request",
            "body": "Категория: FEATURE\nАгенты: @finder → @coder\nЗапрос: test request",
            "status": "running",
        }
        children = [
            {"id": "child_1", "title": "@finder: разведка проект", "status": "done"},
            {"id": "child_2", "title": "@coder: разработка проект", "status": "ready"},
        ]
        state = kb._build_state_from_board(parent, children)
        assert state["request"] == "test request"
        assert state["category"] == "FEATURE"
        assert state["pipeline"] == ["finder", "coder"]
        assert state["completed"] == ["finder"]
        assert state["current_idx"] == 1
        assert state["kanban_parent_id"] == "pipe:abc123"
        assert state["kanban_task_ids"] == {"finder": "child_1", "coder": "child_2"}

    def test_no_completed(self):
        parent = {
            "id": "pipe:abc",
            "title": "🔷  Пайплайн: test",
            "body": "Категория: BUG",
            "status": "ready",
        }
        children = [
            {"id": "c1", "title": "@finder: task", "status": "todo"},
        ]
        state = kb._build_state_from_board(parent, children)
        assert state["completed"] == []
        assert state["current_idx"] == 0

    def test_all_done(self):
        parent = {
            "id": "pipe:abc",
            "title": "🔷  Пайплайн: test",
            "body": "Категория: FEATURE\nАгенты: @finder",
            "status": "done",
        }
        children = [
            {"id": "c1", "title": "@finder: task", "status": "done"},
        ]
        state = kb._build_state_from_board(parent, children)
        assert state["completed"] == ["finder"]
        # current_idx will be 1 (past last) because current_idx < len(pipeline) check
        # Actually: all are done, so current_idx stays -1 → gets promoted to 0
        assert state["current_idx"] == 0

    def test_request_from_body_when_body_has_request(self):
        """When title has generic text and body has 'Запрос:', use body."""
        parent = {
            "id": "pipe:abc",
            "title": "🔷  Пайплайн: Pipeline task",
            "body": "Категория: FEATURE\nАгенты: @finder\nЗапрос: actual user request",
            "status": "running",
        }
        children = []
        state = kb._build_state_from_board(parent, children)
        assert state["request"] == "actual user request"


class TestClaimAndAssign:
    """Tests for _claim_and_assign guard conditions."""

    def test_empty_task_id(self):
        assert kb._claim_and_assign("", "assignee") is False

    def test_empty_assignee(self):
        assert kb._claim_and_assign("task_123", "") is False

    def test_both_empty(self):
        assert kb._claim_and_assign("", "") is False


class TestCleanupStalePipelines:
    """Tests for _cleanup_stale_pipelines — edge cases."""

    def test_no_stale_pipelines(self):
        """When no stale parents exist, returns 0."""
        with mock.patch.object(kb, "_sqlite_select") as mock_select:
            mock_select.return_value = []
            result = kb._cleanup_stale_pipelines(max_age_hours=24)
        assert result == 0

    def test_stale_pipeline_with_no_children_skipped(self):
        """Bug #15: a 'parent' with < 1 child is not a pipeline."""
        with mock.patch.object(kb, "_sqlite_select") as mock_select:
            # First call: find stale
            mock_select.side_effect = [
                [{"id": "stale_1"}],  # _find_active_parent → stale list
                [],  # child link check — no children
            ]
            result = kb._cleanup_stale_pipelines(max_age_hours=24)
        assert result == 0

    def test_stale_pipeline_with_children_is_archived(self):
        """Bug #15: pipeline with 1+ children should be archived."""
        with mock.patch.object(kb, "_sqlite_select") as mock_select, \
             mock.patch.object(kb, "_sqlite_update") as mock_update:
            mock_update.return_value = True
            # First call: find stale
            mock_select.side_effect = [
                [{"id": "stale_1"}],  # stale parents
                [{"child_id": "child_1"}, {"child_id": "child_2"}],  # has children
            ]
            result = kb._cleanup_stale_pipelines(max_age_hours=24)
        assert result == 1
        # Should have completed 2 children + 1 parent = 3 updates
        assert mock_update.call_count >= 3


class TestAgentDescriptions:
    """Tests that AGENT_DESCRIPTIONS cover all AGENT_VERB keys."""

    def test_all_agents_have_descriptions(self):
        for agent in kb._AGENT_VERB:
            assert agent in kb.AGENT_DESCRIPTIONS, (
                f"Agent '{agent}' has _AGENT_VERB but no AGENT_DESCRIPTIONS entry"
            )

    def test_all_descriptions_are_nonempty(self):
        for agent, desc in kb.AGENT_DESCRIPTIONS.items():
            assert len(desc) > 10, f"Agent '{agent}' description too short: {desc}"
