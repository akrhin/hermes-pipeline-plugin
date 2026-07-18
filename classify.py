"""Request classification for Pipeline Plugin.

8 categories with keyword-based detection.
Returns category + full pipeline definition.
"""

# ── Category definitions ─────────────────────────────────────────────────────┘

CATEGORIES = {
    "SECURITY_RELATED": {
        "keywords": [
            "auth", "login", "logout", "password", "token", "session", "cookie",
            "jwt", "oauth", "api key", "secret", "encrypt", "decrypt", "hash",
            "salt", "credential", "permission", "role", "admin", "access control",
            "user data", "private key", "sensitive", "authentic",
            "аутентификац", "авторизац", "парол", "токен", "секрет",
            "шифрова", "безопасност", "доступ", "авториз", "аутентифицир",
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
            if kw in request_lower:
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

    # Pick best category (highest score, ties → first defined wins)
    best = max(scores, key=lambda c: (scores[c], -list(CATEGORIES.keys()).index(c)))

    return {
        "category": best,
        "pipeline": CATEGORIES[best]["pipeline"],
        "matched_keywords": matched[best],
        "description": f"{best.replace('_', ' ').title()} pipeline",
    }
