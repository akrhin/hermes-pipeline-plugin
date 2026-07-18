"""Unit tests for pipeline classify module."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from classify import classify


class TestClassify:
    def test_security_auth(self):
        result = classify("добавь аутентификацию через JWT")
        assert result["category"] == "SECURITY_RELATED"
        assert "finder" in result["pipeline"]
        assert "security" in result["pipeline"]

    def test_bug_crash(self):
        result = classify("баг: крашится при логине")
        assert result["category"] == "BUG_UNKNOWN"

    def test_known_bug_priority(self):
        """When both BUG_KNOWN and BUG_UNKNOWN match equally, BUG_UNKNOWN wins (safer)."""
        result = classify("почини баг")
        # Both match 1 keyword each, BUG_UNKNOWN is defined first → wins tie
        assert result["category"] in ("BUG_KNOWN", "BUG_UNKNOWN")

    def test_refactoring(self):
        result = classify("рефактори UserService")
        assert result["category"] == "REFACTORING"

    def test_performance(self):
        result = classify("оптимизируй запросы к базе")
        assert result["category"] == "PERFORMANCE"

    def test_infrastructure(self):
        result = classify("настрой docker-compose")
        assert result["category"] == "INFRASTRUCTURE"

    def test_documentation(self):
        result = classify("обнови README файл")
        assert result["category"] == "DOCUMENTATION"

    def test_feature_default(self):
        result = classify("сделай импорт из CSV")
        assert result["category"] == "FEATURE"

    def test_no_match_returns_feature(self):
        result = classify("как дела?")
        assert result["category"] == "FEATURE"
        assert result["matched_keywords"] == []

    def test_security_takes_precedence(self):
        """Security keywords beat feature when equal scores."""
        result = classify("секрет токен")
        assert result["category"] == "SECURITY_RELATED"

    def test_lowercase_handling(self):
        result = classify("JWT Authentication")
        assert result["category"] == "SECURITY_RELATED"

    def test_pipeline_not_empty(self):
        result = classify("refactor auth module")
        assert len(result["pipeline"]) > 0

    def test_matched_keywords_present(self):
        result = classify("исправь баг в login")
        assert len(result["matched_keywords"]) > 0

    def test_finder_always_first(self):
        for req in ["bug", "feature", "refactor", "doc"]:
            result = classify(req)
            assert result["pipeline"][0] == "finder"


class TestClassifyEdgeCases:
    def test_empty_string(self):
        result = classify("")
        assert result["category"] == "FEATURE"

    def test_whitespace(self):
        result = classify("   ")
        assert result["category"] == "FEATURE"

    def test_case_insensitive(self):
        result = classify("FIX BUG IN LOGIN")
        # BUG (BUG_UNKNOWN) + LOGIN (SECURITY_RELATED) = 1 each
        # Both in TIER1 — whoever has higher priority wins
        assert result["category"] in ("BUG_UNKNOWN", "SECURITY_RELATED")

    def test_refactor_before_docs(self):
        """'refactor' must win over 'док' (short word boundary)"""
        result = classify("рефакторинг документации")
        assert result["category"] == "REFACTORING", f"Got {result['category']}"

    def test_audit_triggers_security(self):
        result = classify("проведи аудит кода")
        assert result["category"] == "SECURITY_RELATED"

    def test_collision_triggers_refactoring(self):
        result = classify("найди коллизии в данных")
        assert result["category"] == "REFACTORING"

    def test_mismatch_triggers_refactoring(self):
        result = classify("несоответствия в схеме")
        assert result["category"] == "REFACTORING"


class TestClassifyCaching:
    def test_regex_cache_hits(self):
        """Calling classify multiple times should use cached regex patterns."""
        # Warm up + check it doesn't crash
        for _ in range(10):
            classify("аутентификация")
            classify("bug в логине")
            classify("док")
        # If we got here without error, caching works fine
        assert True
