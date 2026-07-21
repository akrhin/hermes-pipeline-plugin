"""Request classification for Pipeline Plugin.

8 categories with keyword-based detection.
Supports multi-label: returns ALL matched categories with merged pipeline.
"""

import re
from functools import lru_cache

# ── Category definitions ─────────────────────────────────────────────────────┘

# Minimum length for plain substring matching
_SHORT_KW_LEN = 5  # strict < 5: "crash"(5) uses substring, "bug"(3) uses word-boundary


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
    if len(kw) < _SHORT_KW_LEN:
        return bool(_make_word_pattern(kw).search(text))
    return kw in text


CATEGORIES = {
    "SECURITY_RELATED": {
        "keywords": [
            "auth",
            "login",
            "logout",
            "password",
            "token",
            "session",
            "cookie",
            "jwt",
            "oauth",
            "api key",
            "secret",
            "encrypt",
            "decrypt",
            "hash",
            "salt",
            "credential",
            "permission",
            "role",
            "admin",
            "access control",
            "user data",
            "private key",
            "sensitive",
            "authentic",
            "аутентификац",
            "авторизац",
            "парол",
            "токен",
            "секрет",
            "шифрова",
            "безопасност",
            "доступ",
            "авториз",
            "аутентифицир",
            "уязвим",
            "vulnerability",
            "xss",
            "csrf",
            "rbac",
            "hack",
            "sql injection",
            "инъекц",
        ],
        "pipeline": [
            "finder",
            "analyst",
            "researcher",
            "architect",
            "planner",
            "coder",
            "reviewer",
            "security",
            "integration",
            "tester",
            "documenter",
        ],
    },
    "BUG_UNKNOWN": {
        "keywords": [
            "баг",
            "bug",
            "пада",
            "crash",
            "ошибк",
            "error",
            "не работает",
            "сломал",
            "сломано",
            "broken",
            "exception",
            "вылета",
            "зависа",
            "не грузи",
            "не открыва",
            "не сохраня",
            "не отправля",
            "крашит",
            "краш",
            "упал",
            "валит",
            "глюк",
            "glitch",
            "некоррект",
            "неправильн",
            "regression",
            "дефект",
            "defect",
            "traceback",
            "стек трейс",
            "фейл",
            "fail",
            "поломал",
        ],
        "pipeline": ["finder", "debugger", "fixer", "reviewer", "tester"],
    },
    "BUG_KNOWN": {
        "keywords": [
            "исправ",
            "fix",
            "почини",
            "поправ",
            "пофикс",
            "чини",
            "реши проблем",
        ],
        "pipeline": ["finder", "fixer", "reviewer", "tester"],
    },
    "REFACTORING": {
        "keywords": [
            "рефактор",
            "refactor",
            "перепиш",
            "передела",
            "улучш",
            "почисти",
            "упрости",
            "reorganize",
            "clean",
            "коллизи",
            "collision",
            "несоответств",
            "mismatch",
            "дублирова",
            "duplicate",
            "duplication",
            "cohesion",
            "связанност",
            "coupling",
            "зацеплен",
            "мертв",
            "dead code",
            "unused",
            "неиспользу",
            "lint",
            "code smell",
            "style",
            "горяч",
            "пробел",
            "реструктуриз",
            "restructure",
            "вынеси",
            "modularize",
            "раздели",
            "extract",
            "выдел",
            "аудит",
            "audit",
        ],
        "pipeline": ["finder", "analyst", "refactorer", "reviewer", "integration", "tester"],
    },
    "PERFORMANCE": {
        "keywords": [
            "оптимиз",
            "optimize",
            "тормоз",
            "медлен",
            "slow",
            "быстродейств",
            "производител",
            "performance",
            "memory",
            "память",
            "скорост",
            "latency",
            "задержк",
            "cache",
            "кеш",
            "кэш",
            "бенчмарк",
            "benchmark",
            "load test",
            "нагрузк",
            "bottleneck",
            "узк",
            "подвиса",
        ],
        "pipeline": ["finder", "analyst", "optimizer", "reviewer", "tester"],
    },
    "INFRASTRUCTURE": {
        "keywords": [
            "ci/cd",
            "ci cd",
            "docker",
            "депло",
            "deploy",
            "конфиг",
            "config",
            "devops",
            "инфраструктур",
            "infrastructure",
            "сервер",
            "server",
            "nginx",
            "postgres",
            "redis",
            "rabbit",
            "kafka",
            "kubernetes",
            "k8s",
            "helm",
            "terraform",
            "ansible",
            "мониторинг",
            "monitoring",
            "prometheus",
            "grafana",
            "лог",
            "log",
            "backup",
            "бэкап",
            "репликац",
            "replication",
            "масштабир",
            "scale",
            "нагрузк",
            "прокси",
            "proxy",
            "dns",
            "ssl",
        ],
        "pipeline": ["finder", "devops", "reviewer", "tester"],
    },
    "DOCUMENTATION": {
        "keywords": [
            "документац",
            "documentation",
            "readme",
            "api doc",
            "док",
            "описани",
            "комментар",
            "comment",
            "guide",
            "инструкц",
            "changelog",
            "wiki",
            "contribut",
            "лицензи",
            "license",
            "migration",
            "миграц",
            "архитектур",
            "architecture",
            "design doc",
            "spec",
            "спецификац",
        ],
        "pipeline": ["finder", "documenter"],
    },
    "FEATURE": {
        "keywords": [
            "добав",
            "add",
            "сдела",
            "create",
            "реализу",
            "implement",
            "нов",
            "new",
            "функци",
            "function",
            "модул",
            "module",
            "напиш",
            "write",
            "build",
            "внедр",
            "разработ",
            "develop",
            "расшир",
            "extend",
            "интеграц",
            "integration",
            "поддержк",
            "support",
            "плаг",
            "plugin",
            "фич",
            "feature",
            "возможност",
            "capability",
            "разработа",
        ],
        "pipeline": [
            "finder",
            "analyst",
            "architect",
            "planner",
            "coder",
            "reviewer",
            "integration",
            "tester",
            "documenter",
        ],
    },
}


# Порядок приоритетов для устранения дубликатов в `pipeline`
# Специализированные агенты должны быть включены если их категория совпала
_CATEGORY_SPECIFIC_AGENTS = {
    "SECURITY_RELATED": {"security"},
    "BUG_UNKNOWN": {"debugger", "fixer"},
    "BUG_KNOWN": {"fixer"},
    "REFACTORING": {"refactorer"},
    "PERFORMANCE": {"optimizer"},
    "INFRASTRUCTURE": {"devops"},
}

CATEGORY_EMOJI = {
    "BUG_KNOWN": "\U0001f41b",
    "BUG_UNKNOWN": "\U0001f41b",
    "SECURITY_RELATED": "\U0001f512",
    "REFACTORING": "\U0001f527",
    "PERFORMANCE": "\u26a1",
    "INFRASTRUCTURE": "\U0001f3d7\ufe0f",
    "FEATURE": "\u2728",
    "DOCUMENTATION": "\U0001f4da",
}

# Общие агенты, которые есть почти во всех категориях
_COMMON_AGENTS = {"finder", "analyst", "architect", "planner", "coder",
                  "reviewer", "integration", "tester", "documenter"}

# Tiebreaker priority (lower = higher priority)
_PRIORITY_ORDER = [
    "BUG_KNOWN", "BUG_UNKNOWN", "SECURITY_RELATED",
    "REFACTORING", "PERFORMANCE",
    "INFRASTRUCTURE", "FEATURE",
    "DOCUMENTATION",
]
_PRIORITY_WEIGHTS = [10, 10, 10, 5, 5, 2, 2, 3]
_MIN_SCORE = 1  # минимальное кол-во совпадений чтобы категория считалась


def _merge_pipelines(matched_categories: list[str]) -> list[str]:
    """Объединяет пайплайны нескольких категорий в один упорядоченный список.

    Правила:
    1. Общие агенты (finder, coder, reviewer, tester, documenter и т.д.) — идут в
       порядке их первого появления в PREDEFINED_ORDER.
    2. Специализированные агенты (security, debugger, fixer, refactorer, optimizer,
       devops) — добавляются на свои позиции:
       - security → после reviewer
       - debugger → после finder
       - fixer → после debugger/finder
       - refactorer → после analyst
       - optimizer → после analyst
       - devops → после finder
    """

    # Агенты, которые могут быть задействованы (все из совпавших категорий)
    # + общие обязательные
    all_agents = set()
    for cat in matched_categories:
        all_agents.update(CATEGORIES[cat]["pipeline"])

    predefined = [
        "finder",
        "debugger",
        "fixer",
        "analyst",
        "researcher",
        "refactorer",
        "optimizer",
        "architect",
        "planner",
        "coder",
        "devops",
        "reviewer",
        "security",
        "integration",
        "tester",
        "documenter",
    ]

    return [a for a in predefined if a in all_agents]


def _get_category_name(cat_name: str) -> str:
    """Human-readable category name."""
    return cat_name.replace("_", " ").title()


def classify(request: str) -> dict:
    """
    Classify a user request into pipeline categories.

    Multi-label: returns ALL categories that match keywords.
    Pipelines are merged unique+ordered.

    Returns:
    {
        "categories": ["FEATURE", "SECURITY_RELATED"],  # all matched
        "primary": "FEATURE",  # highest priority matched category
        "pipeline": ["finder", "analyst", "architect", "planner", "coder",
                     "reviewer", "security", "integration", "tester", "documenter"],
        "matched_keywords": {"FEATURE": ["добав"], "SECURITY_RELATED": ["аудит"]},
        "description": "Feature + Security pipeline"
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
        if score >= _MIN_SCORE:
            scores[cat_name] = score
            matched[cat_name] = matched_kw

    if not scores:
        # Default to feature
        return {
            "categories": ["FEATURE"],
            "primary": "FEATURE",
            "pipeline": CATEGORIES["FEATURE"]["pipeline"],
            "matched_keywords": {},
            "description": "Default feature pipeline (no category matched)",
            "emoji": "📋",
        }

    # ── Multi-label: all matched categories ──
    matched_categories = list(scores.keys())

    # Determine primary (highest priority category with most keyword matches)
    def priority(cat):
        raw_score = scores[cat]
        try:
            pos = _PRIORITY_ORDER.index(cat)
            weight = _PRIORITY_WEIGHTS[pos]
        except ValueError:
            pos = 99
            weight = 1
        return (-pos, raw_score, raw_score * weight)

    primary = max(matched_categories, key=priority)

    # ── Merge pipelines ──
    merged_pipeline = _merge_pipelines(matched_categories)

    # Build description
    desc_parts = []
    for cat in matched_categories:
        cat_desc = _get_category_name(cat)
        kw = matched[cat]
        if kw:
            cat_desc += f" ({', '.join(kw[:3])})"
        desc_parts.append(cat_desc)

    return {
        "categories": matched_categories,
        "primary": primary,
        "pipeline": merged_pipeline,
        "matched_keywords": matched,
        "description": " + ".join(desc_parts),
        "emoji": CATEGORY_EMOJI.get(primary, "📋"),
    }
