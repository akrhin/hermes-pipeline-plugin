"""Edge-case tests for kanban.py — resume, parse helpers, idempotency keys, SQLite pool."""

from __future__ import annotations

import json
import os
import sys
from contextlib import contextmanager
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import kanban as kb


# ── Helper: switch kanban mode for SQLite-specific tests ───────────────────────


@contextmanager
def _kanban_mode(mode: str):
    """Temporarily switch config.yaml kanban_mode and reload kanban module."""
    import importlib
    import re
    cfg_path = os.path.join(os.path.dirname(kb.__file__), "config.yaml")
    with open(cfg_path) as f:
        orig = f.read()
    if re.search(r"kanban_mode:\s*\w+", orig):
        new = re.sub(r"kanban_mode:\s*\w+", f"kanban_mode: {mode}", orig)
    else:
        new = orig + f"\npipeline:\n  kanban_mode: {mode}\n"
    with open(cfg_path, "w") as f:
        f.write(new)
    kb._KANBAN_MODE = None
    importlib.reload(kb)
    try:
        yield
    finally:
        with open(cfg_path, "w") as f:
            f.write(orig)
        kb._KANBAN_MODE = None
        importlib.reload(kb)


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


# ── Additional edge-case tests for functions declared in kanban_common.py ──


class TestExtractTargetEdgeCases:
    """Extended edge cases for _extract_target."""

    def test_known_name_embedded_in_longer_string(self):
        """Known name embedded inside a larger string should still match."""
        result = kb._extract_target("fix hermes-pipeline-plugin-extra-feature")
        assert result == "hermes-pipeline-plugin"

    def test_known_project_preferred_over_preposition_match(self):
        """Known pipeline/plugin should match before preposition targeting."""
        result = kb._extract_target("фикс в hermes-pipeline-plugin")
        assert result == "hermes-pipeline-plugin"

    def test_known_preferred_over_first_word(self):
        """Known name anywhere in string is preferred over first-word fallback."""
        result = kb._extract_target("напиши код для pipeline")
        assert result == "pipeline"

    def test_preposition_for_cyrillic(self):
        """Preposition 'для' returns the following word."""
        result = kb._extract_target("код для оптимизации бд")
        assert result == "оптимизации"

    def test_preposition_on(self):
        """Preposition 'на' returns the following word."""
        result = kb._extract_target("работа на сервере")
        assert result == "сервере"

    def test_preposition_with_hyphenated_word(self):
        """Preposition captures hyphenated words too."""
        result = kb._extract_target("рефакторинг в models-new.py")
        assert result == "models-new.py"

    def test_only_numbers_and_symbols(self):
        """Request with only numbers/symbols falls through to 'проект'."""
        result = kb._extract_target("123 !@# $%^")
        assert result == "проект"

    def test_first_word_two_chars_only(self):
        """When no word has 3+ chars, return 'проект'."""
        result = kb._extract_target("on it")
        assert result == "проект"

    def test_whitespace_only(self):
        """Whitespace-only request returns 'проект'."""
        result = kb._extract_target("   \t  ")
        assert result == "проект"

    def test_request_single_russian_word(self):
        """Single word of 3+ Russian chars returns that word."""
        result = kb._extract_target("тестирование")
        assert result == "тестирование"

    def test_request_single_english_word(self):
        """Single word of 3+ English chars returns that word."""
        result = kb._extract_target("testing")
        assert result == "testing"

    def test_request_with_colon(self):
        """Request containing colon does not cause split issues — first 3+ char word wins."""
        result = kb._extract_target("BUG: fix login")
        assert result == "bug"  # no known name, no preposition, first 3+ char word is 'bug'

    def test_known_config_yaml(self):
        """config.yaml is recognised as a known name."""
        result = kb._extract_target("update config.yaml")
        assert result == "config.yaml"

    def test_known_kanban_db(self):
        """kanban.db is recognised as a known name."""
        result = kb._extract_target("clean kanban.db")
        assert result == "kanban.db"

    def test_known_architecture_md(self):
        """agents.md / architecture.md are recognised as known names."""
        result = kb._extract_target("update agents.md")
        assert result == "agents.md"

    def test_known_dashboard(self):
        """дашборд is recognised as a known name."""
        result = kb._extract_target("показать дашборд")
        assert result == "дашборд"

    def test_preposition_no_space_after(self):
        """Preposition without a following word falls through."""
        result = kb._extract_target("работа в")
        # 'в' with nothing after → falls to first 3+ char word
        assert result == "работа"

    def test_first_word_with_underscore_prefix(self):
        """Word starting with underscore doesn't match via \\b — falls through to next word."""
        result = kb._extract_target("_debug module")
        assert result == "module"  # \b doesn't match before _ since _ is \w


class TestParentTaskIdEdgeCases:
    """Extended edge cases for parent_task_id."""

    def test_prefix_always_pipe(self):
        """Result always starts with pipe:."""
        assert kb.parent_task_id([], "").startswith("pipe:")
        assert kb.parent_task_id(["finder"], "test").startswith("pipe:")

    def test_empty_pipeline_list(self):
        """Empty pipeline list still produces a valid key."""
        key = kb.parent_task_id([], "test request")
        assert key.startswith("pipe:")
        assert len(key) == 5 + 12  # "pipe:" + 12 hex chars

    def test_empty_request(self):
        """Empty request still produces a valid, deterministic key."""
        key1 = kb.parent_task_id(["finder"], "")
        key2 = kb.parent_task_id(["finder"], "")
        assert key1 == key2
        assert key1.startswith("pipe:")

    def test_both_empty(self):
        """Both empty still produces a deterministic key."""
        key = kb.parent_task_id([], "")
        assert key.startswith("pipe:")
        assert len(key) == 5 + 12  # 17 chars

    def test_very_long_agent_list(self):
        """Many agents in pipeline still produce a valid hash."""
        agents = [f"agent_{i}" for i in range(50)]
        key = kb.parent_task_id(agents, "request")
        assert key.startswith("pipe:")
        assert len(key) == 17

    def test_different_pipeline_same_request_different_keys(self):
        """Different agent lists with same request produce different keys."""
        k1 = kb.parent_task_id(["finder", "coder"], "request")
        k2 = kb.parent_task_id(["coder", "finder"], "request")
        assert k1 != k2

    def test_request_trimmed_to_40_chars(self):
        """Request is trimmed to 40 chars; requests differing after 40 produce same key."""
        k1 = kb.parent_task_id(["finder"], "a" * 40 + "extra")
        k2 = kb.parent_task_id(["finder"], "a" * 40 + "other")
        assert k1 == k2

    def test_request_under_40_not_trimmed(self):
        """Short request under 40 chars is used as-is."""
        k1 = kb.parent_task_id(["finder"], "short")
        k2 = kb.parent_task_id(["finder"], "short")
        assert k1 == k2

    def test_agents_with_underscores(self):
        """Agent names containing underscores are handled correctly."""
        k = kb.parent_task_id(["code_reviewer", "security_audit"], "test")
        assert k.startswith("pipe:")
        assert len(k) == 17


class TestChildIdEdgeCases:
    """Extended edge cases for child_id."""

    def test_empty_parent_ikey(self):
        """Empty parent idempotency key still produces a result."""
        cid = kb.child_id("", "coder")
        assert cid == ":coder:r0"

    def test_empty_agent(self):
        """Empty agent still produces a result."""
        cid = kb.child_id("pipe:abc", "")
        assert cid == "pipe:abc::r0"

    def test_default_round_zero(self):
        """Default round_num is 0."""
        explicit = kb.child_id("pipe:abc", "coder", round_num=0)
        default = kb.child_id("pipe:abc", "coder")
        assert explicit == default

    def test_both_empty(self):
        """Both empty parent_ikey and agent produce a minimal result."""
        cid = kb.child_id("", "")
        assert cid == "::r0"

    def test_pattern_format(self):
        """Matches expected format: {parent}:{agent}:r{round}."""
        cid = kb.child_id("pipe:abc123def", "coder", round_num=2)
        assert cid == "pipe:abc123def:coder:r2"

    def test_negative_round(self):
        """Negative round number is accepted as-is."""
        cid = kb.child_id("pipe:abc", "coder", round_num=-1)
        assert cid == "pipe:abc:coder:r-1"

    def test_agent_with_special_chars(self):
        """Agent name with special characters is preserved."""
        cid = kb.child_id("pipe:abc", "code-reviewer", round_num=0)
        assert cid == "pipe:abc:code-reviewer:r0"

    def test_long_parent_ikey(self):
        """Long parent key is preserved in the child key."""
        long_key = "pipe:" + "a" * 128
        cid = kb.child_id(long_key, "coder")
        assert cid == f"{long_key}:coder:r0"
        assert len(cid) > 50


class TestParseCategoriesEdgeCases:
    """Extended edge cases for _parse_categories."""

    def test_single_category_with_colon_inside_value(self):
        """Category value containing a colon is handled (takes after first colon)."""
        cats, primary = kb._parse_categories("Категория: FEATURE:IMPORTANT\n")
        assert "FEATURE:IMPORTANT" in cats
        assert primary == "FEATURE:IMPORTANT"

    def test_category_empty_value_skipped(self):
        """'Категория:' with empty value after colon is skipped."""
        cats, primary = kb._parse_categories("Категория:\nMore text")
        assert cats == []
        assert primary == ""

    def test_categories_empty_values_skipped(self):
        """'Категории:' with trailing comma produces empty items that are skipped."""
        cats, primary = kb._parse_categories("Категории: BUG,\n")
        assert cats == ["BUG"]
        assert primary == "BUG"

    def test_multiple_category_lines(self):
        """Multiple 'Категория:' lines all contribute."""
        cats, primary = kb._parse_categories(
            "Категория: SECURITY\nКатегория: PERFORMANCE\n"
        )
        assert cats == ["SECURITY", "PERFORMANCE"]
        assert primary == "SECURITY"

    def test_both_singular_and_plural_lines(self):
        """Both 'Категория:' and 'Категории:' lines contribute."""
        cats, primary = kb._parse_categories(
            "Категория: SECURITY\nКатегории: BUG, PERFORMANCE\n"
        )
        assert cats == ["SECURITY", "BUG", "PERFORMANCE"]
        assert primary == "SECURITY"

    def test_whitespace_in_category_value(self):
        """Leading/trailing whitespace in category values is stripped."""
        cats, primary = kb._parse_categories("Категория:   SECURITY   \n")
        assert cats == ["SECURITY"]
        assert primary == "SECURITY"

    def test_category_line_embedded_in_body(self):
        """Category line surrounded by other content is found."""
        body = "First line\nКатегория: FEATURE\nLast line"
        cats, primary = kb._parse_categories(body)
        assert cats == ["FEATURE"]
        assert primary == "FEATURE"

    def test_case_sensitivity(self):
        """Lowercase 'категория:' does NOT match (case-sensitive)."""
        cats, primary = kb._parse_categories("категория: BUG\n")
        # The code uses startswith("Категория:") with capital К, so lowercase won't match
        assert cats == []
        assert primary == ""


class TestBuildStateFromBoardEdgeCases:
    """Extended edge cases for _build_state_from_board."""

    def test_empty_children_list(self):
        """No children — pipeline is empty, no completed tasks."""
        parent = {
            "id": "pipe:xyz",
            "title": "🔷  Пайплайн: test run",
            "body": "Категория: FEATURE\nАгенты: @finder → @coder",
            "status": "running",
        }
        state = kb._build_state_from_board(parent, [])
        assert state["request"] == "test run"
        assert state["pipeline"] == ["finder", "coder"]
        assert state["completed"] == []
        assert state["kanban_task_ids"] == {}

    def test_non_at_title_children_ignored(self):
        """Children without @ prefix are ignored in pipeline/status tracking."""
        parent = {
            "id": "pipe:xyz",
            "title": "🔷  Пайплайн: test",
            "body": "Категория: BUG\nАгенты: @finder",
            "status": "running",
        }
        children = [
            {"id": "c1", "title": "@finder: разведка", "status": "done"},
            {"id": "c2", "title": "Note: something else", "status": "done"},
            {"id": "c3", "title": "", "status": "done"},
        ]
        state = kb._build_state_from_board(parent, children)
        assert state["kanban_task_ids"] == {"finder": "c1"}
        assert state["completed"] == ["finder"]

    def test_empty_body_no_categories(self):
        """No body lines with Категория: — category falls through to empty."""
        parent = {
            "id": "pipe:abc",
            "title": "🔷  Пайплайн: test",
            "body": "",
            "status": "ready",
        }
        state = kb._build_state_from_board(parent, [])
        assert state["category"] == ""
        assert state["pipeline"] == []

    def test_request_from_title_when_no_body_request(self):
        """When body has no 'Запрос:', use title-stripped value."""
        parent = {
            "id": "pipe:abc",
            "title": "🔷  Пайплайн: user request text",
            "body": "Категория: FEATURE",
            "status": "running",
        }
        state = kb._build_state_from_board(parent, [])
        assert state["request"] == "user request text"

    def test_body_request_overrides_title(self):
        """When body has 'Запрос:', it overrides the title-derived request."""
        parent = {
            "id": "pipe:abc",
            "title": "🔷  Пайплайн: Generic pipeline",
            "body": "Категория: FEATURE\nЗапрос: actual user request here",
            "status": "running",
        }
        state = kb._build_state_from_board(parent, [])
        assert state["request"] == "actual user request here"

    def test_all_ready_first_agent_is_current(self):
        """When all agents are ready/todo, current_idx points to first agent."""
        parent = {
            "id": "pipe:abc",
            "title": "🔷  Пайплайн: test",
            "body": "Категория: FEATURE\nАгенты: @finder → @coder → @tester",
            "status": "running",
        }
        children = [
            {"id": "c1", "title": "@finder: разведка", "status": "todo"},
            {"id": "c2", "title": "@coder: разработка", "status": "ready"},
            {"id": "c3", "title": "@tester: тесты", "status": "ready"},
        ]
        state = kb._build_state_from_board(parent, children)
        assert state["current_idx"] == 0

    def test_mixed_statuses_correct_current(self):
        """First non-done agent is current_idx."""
        parent = {
            "id": "pipe:abc",
            "title": "🔷  Пайплайн: test",
            "body": "Категория: FEATURE\nАгенты: @finder → @coder → @tester",
            "status": "running",
        }
        children = [
            {"id": "c1", "title": "@finder: разведка", "status": "done"},
            {"id": "c2", "title": "@coder: разработка", "status": "running"},
            {"id": "c3", "title": "@tester: тесты", "status": "ready"},
        ]
        state = kb._build_state_from_board(parent, children)
        assert state["completed"] == ["finder"]
        assert state["current_idx"] == 1

    def test_all_done_current_idx_forced_to_zero(self):
        """When all agents are done, current_idx defaults to 0."""
        parent = {
            "id": "pipe:abc",
            "title": "🔷  Пайплайн: test",
            "body": "Категория: FEATURE\nАгенты: @finder → @coder",
            "status": "done",
        }
        children = [
            {"id": "c1", "title": "@finder: разведка", "status": "done"},
            {"id": "c2", "title": "@coder: разработка", "status": "done"},
        ]
        state = kb._build_state_from_board(parent, children)
        assert state["completed"] == ["finder", "coder"]
        assert state["current_idx"] == 0

    def test_minimal_parent_data(self):
        """Resilient to minimal parent with no title/body/content."""
        parent = {"id": "pipe:min", "title": "", "body": "", "status": "ready"}
        state = kb._build_state_from_board(parent, [])
        assert state["request"] == ""  # empty title after strip
        assert state["category"] == ""
        assert state["kanban_parent_id"] == "pipe:min"
        assert state["pipeline"] == []

    def test_children_with_empty_title(self):
        """Resilient to children with empty/None title — they are ignored."""
        parent = {
            "id": "pipe:abc",
            "title": "🔷  Пайплайн: test",
            "body": "Категория: FEATURE\nАгенты: @finder",
            "status": "running",
        }
        children = [
            {"id": "c1", "title": "@finder: разведка", "status": "done"},
            {"id": "c2", "title": "", "status": "done"},
            {"id": "c3", "title": None, "status": "done"},
        ]
        state = kb._build_state_from_board(parent, children)
        # Only c1 has a valid @-title
        assert state["kanban_task_ids"] == {"finder": "c1"}
        assert state["completed"] == ["finder"]

    def test_state_has_round_zero(self):
        """State always initializes round to 0."""
        parent = {
            "id": "pipe:abc",
            "title": "🔷  Пайплайн: test",
            "body": "",
            "status": "ready",
        }
        state = kb._build_state_from_board(parent, [])
        assert state["round"] == 0

    def test_findings_restored_from_body(self):
        """Findings in parent body #Findings: block are restored."""
        parent = {
            "id": "pipe:abc",
            "title": "🔷  Пайплайн: test",
            "body": (
                "Категория: SECURITY\n"
                "Агенты: @security\n"
                '#Findings:[{"severity":"P0","file":"x.py","category":"sec"}]\n'
            ),
            "status": "done",
        }
        children = [{"id": "c1", "title": "@security: audit", "status": "done"}]
        state = kb._build_state_from_board(parent, children)
        assert len(state["findings"]) == 1
        assert state["findings"][0]["severity"] == "P0"

    def test_pipeline_from_body_vs_children_consistency(self):
        """Pipeline order parsed from body matches child task mapping."""
        parent = {
            "id": "pipe:abc",
            "title": "🔷  Пайплайн: test",
            "body": "Категория: FEATURE\nАгенты: @tester → @coder → @finder",
            "status": "running",
        }
        children = [
            {"id": "c1", "title": "@tester: тесты", "status": "done"},
            {"id": "c2", "title": "@coder: разработка", "status": "running"},
            {"id": "c3", "title": "@finder: разведка", "status": "ready"},
        ]
        state = kb._build_state_from_board(parent, children)
        assert state["pipeline"] == ["tester", "coder", "finder"]
        assert state["completed"] == ["tester"]
        assert state["current_idx"] == 1
        assert state["kanban_task_ids"] == {
            "tester": "c1",
            "coder": "c2",
            "finder": "c3",
        }

    def test_parent_status_preserved_in_state(self):
        """Parent status is preserved in state['status']."""
        parent = {
            "id": "pipe:abc",
            "title": "🔷  Пайплайн: test",
            "body": "",
            "status": "paused",
        }
        state = kb._build_state_from_board(parent, [])
        assert state["status"] == "paused"


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
        with mock.patch("kanban_common._sqlite_select") as mock_select:
            mock_select.return_value = []
            result = kb._cleanup_stale_pipelines(max_age_hours=24)
        assert result == 0

    def test_stale_pipeline_with_no_children_skipped(self):
        """Bug #15: a 'parent' with < 1 child is not a pipeline."""
        with mock.patch("kanban_legacy._sqlite_select") as mock_select:
            # First call: find stale
            mock_select.side_effect = [
                [{"id": "stale_1"}],  # stale parent
                [],  # child link check — no children
            ]
            result = kb._cleanup_stale_pipelines(max_age_hours=24)
        assert result == 0

    def test_stale_pipeline_with_children_is_archived(self):
        """Bug #15: pipeline with 1+ children should be archived."""
        # Switch to legacy mode for this SQLite-specific test
        with _kanban_mode("legacy"):
            import kanban_legacy
            with mock.patch.object(kanban_legacy, "_sqlite_select") as mock_select, \
                 mock.patch.object(kanban_legacy, "_sqlite_update", return_value=True) as mock_update:
                mock_select.side_effect = [
                    [{"id": "stale_1"}],  # stale parents
                    [{"child_id": "child_1"}, {"child_id": "child_2"}],  # has children
                ]
                result = kb._cleanup_stale_pipelines(max_age_hours=24)
                assert result == 1


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
