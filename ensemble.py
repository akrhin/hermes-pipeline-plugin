"""
Best-of-N Ensemble core for Pipeline Plugin v3.0.

Generates N candidate variations, runs them via delegation,
and selects the best via LLM Judge or deterministic fallback.
"""

import logging

import retro as rt

logger = logging.getLogger(__name__)

# ── Default variations (temperature + instruction) ──

VARIATIONS = [
    {"temperature": 0.3, "instruction_extra": "Минимальные изменения. Никакого рефакторинга."},
    {"temperature": 0.5, "instruction_extra": "Чистый код с комментариями и type hints."},
    {"temperature": 0.7, "instruction_extra": "Стандартный production-подход."},
    {"temperature": 0.9, "instruction_extra": "Полное решение с тестами и обработкой ошибок."},
    {"temperature": 1.1, "instruction_extra": "Нестандартный подход. Оптимизации."},
    {"temperature": 0.4, "instruction_extra": "Фокус на безопасности. Проверь граничные случаи."},
    {"temperature": 0.8, "instruction_extra": "Минимальная имплементация. KISS."},
]

# ── Config reading ──

DEFAULT_ENSEMBLE_CONFIG = {
    "enabled": True,
    "default_n": 5,
    "max_n": 10,
    "agents": {
        "coder": {"enabled": True, "n": 5, "judge_mode": "llm"},
        "planner": {"enabled": False, "n": 3, "judge_mode": "deterministic"},
        "tester": {"enabled": False, "n": 3, "judge_mode": "deterministic"},
    },
    "judge": {
        "model": "deepseek-v4-flash",
        "provider": "polza",
    },
    "cost_optimization": {
        "disable_on_round_gt": 1,
    },
}


def read_ensemble_config(config_path: str | None = None) -> dict:
    """Read ensemble config from pipeline config.yaml."""
    import os
    from pathlib import Path

    if not config_path:
        hermes_home = os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes"))
        config_path = str(Path(hermes_home) / "plugins" / "pipeline" / "config.yaml")

    try:
        import yaml

        with open(config_path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)
    except Exception:
        logger.debug("ensemble config not found, using defaults")
        return dict(DEFAULT_ENSEMBLE_CONFIG)

    try:
        pipeline = raw.get("pipeline", {}) if isinstance(raw, dict) else {}
        ec = pipeline.get("ensemble", {})
        if not isinstance(ec, dict):
            return dict(DEFAULT_ENSEMBLE_CONFIG)
        return ec
    except Exception:
        return dict(DEFAULT_ENSEMBLE_CONFIG)


# ── Candidate generation ──


def generate_candidates(state: dict, agent_id: str, n: int = 5) -> list[dict]:
    """Prepare N candidate variation packages for parallel execution.

    Each candidate gets the same task but with different temperature
    and instruction_extra for diversity.
    """
    task = state.get("request", "")
    ctx = state.get("context", {})
    category = state.get("category", "")

    agent_config = read_ensemble_config()
    agent_cfg = agent_config.get("agents", {}).get(agent_id, {})
    n = min(n, agent_cfg.get("n", 5), agent_config.get("max_n", 10), len(VARIATIONS))
    if n < agent_cfg.get("n", 5) and n == len(VARIATIONS):
        logger.warning(
            "Ensemble n=%d capped to %d (only %d variations available). "
            "Add more entries to VARIATIONS in ensemble.py.",
            agent_cfg.get("n", 5),
            n,
            len(VARIATIONS),
        )

    candidates = []
    for i in range(n):
        var = VARIATIONS[i]
        prompt = f"{task}\n\n{var['instruction_extra']}"
        candidates.append(
            {
                "id": f"candidate_{i + 1}",
                "task": prompt,
                "temperature": var["temperature"],
                "instruction_extra": var["instruction_extra"],
                "agent_id": agent_id,
                "context": ctx,
                "category": category,
            }
        )
    return candidates


# ── LLM Judge (full implementation) ──


def _build_judge_prompt(request: str, candidates: list[dict]) -> str:
    """Build the LLM Judge prompt with all candidates."""
    lines = ["Ты — Judge в системе Best-of-N code generation.\n"]
    lines.append(f"## Оригинальная задача\n\n{request}\n")
    lines.append("## Кандидаты\n")
    for c in candidates:
        output = c.get("output", c.get("task", ""))
        lines.append(
            f"### {c['id']} (T={c.get('temperature', '?')})\n"
            f"Стиль: {c.get('instruction_extra', 'стандартный')}\n"
            f"```\n{output[:8000]}\n```\n"
        )

    lines.append("""Оцени каждого кандидата по 4 критериям (0-10):
1. Correctness — решает ли задачу
2. Completeness — всё ли реализовано
3. Code Quality — стиль, чистота, best practices
4. Security — нет ли очевидных уязвимостей

Формат ответа (строго JSON, без markdown-обёртки):
{
  "winner_id": "candidate_3",
  "scores": [{"id": "candidate_1", "total": 35, ...}],
  "rationale": "...",
  "improvements": [...]
}
""")
    return "\n".join(lines)


def judge_candidates(
    request: str,
    candidates: list[dict],
    judge_mode: str = "deterministic",
    judge_config: dict | None = None,
) -> dict:
    """Select the best candidate.

    Two modes:
    - "deterministic" (MVP): picks middle candidate
    - "llm": delegates to LLM Judge
    """
    if not candidates:
        return {"winner_id": None, "rationale": "No candidates"}

    if judge_mode == "deterministic" or len(candidates) <= 2:
        # Fallback: middle candidate
        idx = len(candidates) // 2
        winner = candidates[idx]
        scores = []
        for rank, c in enumerate(candidates):
            # Deterministic scoring: middle candidate = highest score
            dist = abs(rank - idx)
            total = max(40 - dist * 5, 10)
            scores.append(
                {
                    "id": c["id"],
                    "total": total,
                    "correctness": max(10 - dist, 3),
                    "completeness": max(10 - dist, 3),
                    "code_quality": max(10 - dist, 3),
                    "security": max(10 - dist, 3),
                }
            )
        return {
            "winner_id": winner["id"],
            "scores": scores,
            "rationale": (
                f"Selected {winner['id']} (T={winner.get('temperature', '?')}) — "
                f"{winner.get('instruction_extra', 'balanced approach')}"
            ),
            "temperature": winner.get("temperature"),
            "mode": "deterministic",
        }

    if judge_mode == "llm":
        # Build prompt for LLM Judge + delegate args
        prompt = _build_judge_prompt(request, candidates)
        judge_cfg = judge_config or read_ensemble_config().get("judge", {})
        call_args = build_judge_call_args(prompt)
        return {
            "winner_id": None,  # unknown until LLM evaluates
            "rationale": "LLM Judge will evaluate via delegate_task",
            "mode": "llm",
            "judge_prompt": prompt,
            "judge_call_args": call_args,  # ← orchestrator calls delegate_task with this
            "judge_provider": judge_cfg.get("provider", "polza"),
            "judge_model": judge_cfg.get("model", "deepseek-v4-flash"),
        }

    return {
        "winner_id": candidates[0]["id"],
        "rationale": "Unknown mode, picked first",
        "mode": "fallback",
    }


def llm_judge_candidates(
    request: str,
    candidates: list[dict],
    judge_config: dict | None = None,
) -> dict:
    """Evaluate candidates via ctx.llm.complete() — in-process, no delegate_task.

    Uses the same judge prompt as judge_candidates(llm) but calls LLM directly
    through the host's PluginLlm facade. Returns same shape as judge_candidates.
    """
    prompt = _build_judge_prompt(request, candidates)
    judge_cfg = judge_config or read_ensemble_config().get("judge", {})

    # Get ctx from the shared module-level reference
    try:
        from _ctx import get_ctx as _get_ctx

        ctx = _get_ctx()
        if ctx is None:
            # Fallback: return deterministic result
            return judge_candidates(
                request, candidates, judge_mode="deterministic", judge_config=judge_config
            )

        # Call LLM via host-owned facade
        result = ctx.llm.complete(
            messages=[{"role": "user", "content": prompt}],
            model=judge_cfg.get("model", "deepseek-v4-flash"),
            provider=judge_cfg.get("provider", "polza"),
            max_tokens=2000,
            temperature=0.3,
        )
        text = result.text.strip()

        # Parse JSON response
        import json as _json
        import re as _re

        fence_re = _re.compile(r"```(?:json)?\s*(.+?)```", _re.DOTALL | _re.IGNORECASE)
        match = fence_re.search(text)
        if match:
            text = match.group(1).strip()
        parsed = _json.loads(text)

        winner_id = parsed.get("winner_id", candidates[0]["id"])
        rationale = parsed.get("rationale", "LLM Judge")
        scores = parsed.get("scores", [])

        # Log to retro
        try:
            rt.get_retro().ensemble_judge(
                winner=winner_id,
                mode="llm",
                rationale=rationale,
            )
        except Exception:
            pass

        return {
            "winner_id": winner_id,
            "scores": scores,
            "rationale": rationale,
            "mode": "llm",
            "usage": {
                "input_tokens": getattr(result.usage, "input_tokens", 0),
                "output_tokens": getattr(result.usage, "output_tokens", 0),
            },
        }
    except Exception as e:
        logger.warning(
            "llm_judge_candidates failed: %s — falling back to deterministic", e
        )
        return judge_candidates(
            request, candidates, judge_mode="deterministic", judge_config=judge_config
        )


def build_judge_call_args(prompt: str) -> dict:
    """Build delegate_task call args for LLM Judge execution."""
    return {
        "goal": prompt,
    }


def should_use_ensemble(state: dict, agent_id: str) -> bool:
    """Check if ensemble should be enabled for this agent+round."""
    config = read_ensemble_config()
    if not config.get("enabled", True):
        return False

    agent_cfg = config.get("agents", {}).get(agent_id, {})
    if not agent_cfg.get("enabled", False):
        return False

    cost_opt = config.get("cost_optimization", {})
    max_round = cost_opt.get("disable_on_round_gt", 1)
    current_round = state.get("round", 0)
    if current_round > max_round:
        return False

    return True
