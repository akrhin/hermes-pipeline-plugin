"""Request classification for Pipeline Plugin.

8 categories with keyword-based detection.
Returns category + full pipeline definition.
"""

import re
from functools import lru_cache

# ── Category definitions ─────────────────────────────────────────────────────┘

# Minimum length for plain substring matching
_SHORT_KW_LEN = 3  # keywords <= this length use word-boundary matching


@lru_cache(maxsize=256)
def _make_word_pattern(kw: str) -> re.Pattern:
    """Pre-compile word-boundary regex with cache."""
    return re.compile(rf"\b{re.escape(kw)}\b", re.IGNORECASE)


def _kw_matches(kw: str, text: str) -> bool:
    """Check if a keyword matches text.

    Keywords <= 3 chars use word-boundary regex to avoid false positives
    like "док" matching inside "документация".
    Longer keywords use fast substring matching.
    """
    if len(kw) <= _SHORT_KW_LEN:
        return bool(_make_word_pattern(kw).search(text))
    return kw in text


CATEGORIES = {
    "SECURITY_RELATED": {
        "keywords": [
            "auth", "login", "logout", "password", "token", "session", "cookie",
            "jwt", "oauth", "api key", "secret", "encrypt", "decrypt", "hash",
            "salt", "credential", "permission", "role", "admin", "access control",
            "user data", "private key", "sensitive", "authentic",
            "аутентификац", "авторизац", "парол", "токен", "секрет",
            "шифрова", "безопасност", "доступ", "авториз", "аутентифицир",
            "аудит", "audit",
        ],
        "pipeline": [
            "finder", "analyst", "researcher", "architect",
            "planner", "coder", "reviewer", "security", "tester", "documenter",
        ],
    },
    "BUG_UNKNOWN": {
        "keywords": [
            "баг", "bug", "пада", "crash", "ошибк", "error", "не работает",
            "сломал", "broken", "exception", "вылета", "зависа", "не грузи",
            "не открыва", "не сохраня", "не отправля",
        ],
        "pipeline": ["finder", "debugger", "fixer", "reviewer", "tester"],
    },
    "BUG_KNOWN": {
        "keywords": [
            "исправ", "fix", "почини", "поправ",
        ],
        "pipeline": ["finder", "fixer", "reviewer", "tester"],
    },
    "REFACTORING": {
        "keywords": [
            "рефактор", "refactor", "перепиш", "передела", "улучш",
            "почисти", "упрости", "reorganize", "clean",
            "коллизи", "collision", "несоответств", "mismatch",
        ],
        "pipeline": ["finder", "analyst", "refactorer", "reviewer", "tester"],
    },
    "PERFORMANCE": {
        "keywords": [
            "оптимиз", "optimize", "тормоз", "медлен", "slow", "быстродейств",
            "производител", "performance", "memory", "память", "скорост",
        ],
        "pipeline": ["finder", "analyst", "optimizer", "reviewer", "tester"],
    },
    "INFRASTRUCTURE": {
        "keywords": [
            "ci/cd", "ci cd", "docker", "депло", "deploy", "конфиг", "config",
            "devops", "инфраструктур", "infrastructure", "сервер", "server",
            "nginx", "postgres", "redis", "rabbit", "kafka",
        ],
        "pipeline": ["finder", "devops", "reviewer", "tester"],
    },
    "DOCUMENTATION": {
        "keywords": [
            "документац", "documentation", "readme", "api doc", "док",
            "описани", "комментар", "comment", "guide", "инструкц",
        ],
        "pipeline": ["finder", "documenter"],
    },
    "FEATURE": {
        "keywords": [
            "добав", "add", "сдела", "create", "реализу", "implement",
            "нов", "new", "функци", "function", "модул", "module",
            "напиш", "write", "build",
        ],
        "pipeline": [
            "finder", "analyst", "architect", "planner",
            "coder", "reviewer", "tester", "documenter",
        ],
    },
}


def classify(request: str) -> dict:
    """
    Classify a user request into a pipeline category.

    Scoring:
    - Keywords <= 3 chars use word-boundary matching
    - Longer keywords use substring matching
    - Ties broken by category priority tiers
      (BUG_UNKNOWN > BUG_KNOWN > SECURITY > REFACTORING > PERFORMANCE >
       INFRASTRUCTURE > FEATURE > DOCUMENTATION)

    Returns:
    {
        "category": "FEATURE",
        "pipeline": ["finder", "analyst", ...],
        "matched_keywords": ["добав"],
        "description": "New feature pipeline"
    }
    """
    request_lower = request.lower()

    # Score each category by keyword matches
    scores = {}
    matched = {}
    for cat_name, cat_def in CATEGORIES.items():
        score = 0
        matched_kw = []
        for kw in cat_def["keywords"]:
            if _kw_matches(kw, request_lower):
                score += 1
                matched_kw.append(kw)
        if score > 0:
            scores[cat_name] = score
            matched[cat_name] = matched_kw

    if not scores:
        # Default to feature
        return {
            "category": "FEATURE",
            "pipeline": CATEGORIES["FEATURE"]["pipeline"],
            "matched_keywords": [],
            "description": "Default feature pipeline (no category matched)",
        }

    # Tiebreaker priority: prefer more specific categories
    # Weight: type of category matters more than raw keyword count
    tier1 = {"BUG_UNKNOWN", "BUG_KNOWN", "SECURITY_RELATED"}  # safety-critical
    tier2 = {"REFACTORING", "PERFORMANCE"}                     # structural
    tier3 = {"INFRASTRUCTURE", "FEATURE"}                      # general

    def priority(cat):
        """Higher priority = more urgent category."""
        raw_score = scores[cat]
        if cat in tier1:
            return (raw_score * 10, raw_score)
        elif cat in tier2:
            return (raw_score * 5, raw_score)
        elif cat in tier3:
            return (raw_score * 2, raw_score)
        else:  # DOCUMENTATION
            return (raw_score, 0)

    best = max(scores, key=priority)

    return {
        "category": best,
        "pipeline": CATEGORIES[best]["pipeline"],
        "matched_keywords": matched[best],
        "description": f"{best.replace('_', ' ').title()} pipeline",
    }
