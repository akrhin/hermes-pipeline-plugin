"""Pipeline Plugin v3.7.2 — all tool handlers.

Extracted from __init__.py (was 892 lines) in v3.7.2 refactoring.
12 handlers: classify, convergence, save, load, clear, resume,
advance, prompt, model, run_agent, ensemble_run, ensemble_judge.
+ _build_agent_prompt, AGENT_CONTEXT_FIELDS, hot-reload model config.
"""

import json
import logging
import os
import sys
import traceback

import classify
import convergence as cv
import kanban as kb
import retro as rt

logger = logging.getLogger(__name__)


def _get_plugin_dir() -> str:
    """Resolve PLUGIN_DIR dynamically — supports test monkey-patching of __init__.PLUGIN_DIR."""
    # Look up the parent __init__ module to get PLUGIN_DIR (test-patchable)
    parent = sys.modules.get("__init__")
    if parent is not None and hasattr(parent, "PLUGIN_DIR"):
        return parent.PLUGIN_DIR
    # Fallback: compute from our own location
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ── Import ensemble ──────────────────────────────────────────────────────────


def _import_ensemble():
    """Import ensemble functions — works both as plugin and direct import."""
    try:
        from .ensemble import generate_candidates as ec
        from .ensemble import judge_candidates as ej
        from .ensemble import should_use_ensemble as se
        from .ensemble import read_ensemble_config as re
        return ec, ej, se, re
    except ImportError:
        from ensemble import generate_candidates as ec
        from ensemble import judge_candidates as ej
        from ensemble import should_use_ensemble as se
        from ensemble import read_ensemble_config as re
        return ec, ej, se, re


(
    ensemble_generate_candidates,
    ensemble_judge_candidates,
    should_use_ensemble,
    read_ensemble_config,
) = _import_ensemble()


# ── Handlers ─────────────────────────────────────────────────────────────────


def handle_classify(args, **kwargs):
    try:
        request = args["request"]
        retro = rt.get_retro()
        retro.log("classify", request=request[:80])
        result = classify.classify(request)
        retro.log(
            "classify_result",
            categories=result.get("categories", []),
            primary=result.get("primary", "?"),
            agents=len(result.get("pipeline", [])),
        )
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e), "traceback": traceback.format_exc()})


def handle_convergence(args, **kwargs):
    """Evaluate convergence. Findings posted to kanban board state in-memory."""
    try:
        state = args["state"]
        findings = args.get("findings")
        if findings is None and not state.get("findings"):
            return json.dumps(
                {
                    "decision": "unknown",
                    "reason": "No findings — cannot evaluate",
                    "round": state.get("round", 0),
                }
            )
        result = cv.evaluate_convergence(state, findings)
        kb.on_convergence(state, result)

        retro = rt.get_retro()
        retro.convergence(
            round=result.get("round", 0),
            decision=result.get("decision", "?"),
            p0=result.get("p0_count", 0),
            p1=result.get("p1_count", 0),
            p2=result.get("p2_count", 0),
            fingerprint=state.get("findings_fingerprint", ""),
            reason=result.get("reason", ""),
        )
        if findings:
            active = [
                f for f in findings if f.get("status", "open") not in ("fixed", "accepted", "none")
            ]
            p0 = len([f for f in active if f["severity"] == "P0"])
            p1 = len([f for f in active if f["severity"] == "P1"])
            p2 = len([f for f in findings if f["severity"] == "P2"])
            fixed = len([f for f in findings if f.get("status") == "fixed"])
            accepted = len([f for f in findings if f.get("status") == "accepted"])
            retro.findings_event(p0, p1, p2, fixed=fixed, accepted=accepted)
            retro.findings_detail(findings)

        decision = result.get("decision", "")
        if decision in ("maxed_out", "stuck") and rt.DEFAULT_RETRO_CONFIG.get("auto_analyze", True):
            config = rt._read_retro_config()
            if config.get("auto_analyze", True):
                events = rt.get_latest_log(limit=1)
                analysis = rt.build_analysis_prompt(events)
                retro.log("auto_analysis", decision=decision, analysis=analysis[:500])

        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return json.dumps(
            {"error": str(e), "traceback": traceback.format_exc()}, ensure_ascii=False
        )


def handle_save(args, **kwargs):
    """Create/update kanban task tree. Idempotent."""
    try:
        state = args["state"]
        state = kb.create_task_tree(state)

        parent_id = state.get("kanban_parent_id")
        retro = rt.get_retro(run_id=parent_id or "")
        retro.log(
            "pipeline_start",
            category=state.get("category", ""),
            agents=len(state.get("pipeline", [])),
            request=(state.get("request", "") or "")[:80],
        )

        return json.dumps(
            {
                "status": "ok",
                "kanban_parent_id": state.get("kanban_parent_id"),
                "kanban_task_ids": state.get("kanban_task_ids", {}),
            },
            ensure_ascii=False,
        )
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


def handle_load(args, **kwargs):
    """Scan kanban board for active pipeline state."""
    try:
        state = kb.scan_board()
        if state is None:
            rt.get_retro().log("pipeline_load", found=False)
            return json.dumps(None)
        rt.get_retro().log("pipeline_load", found=True, pipeline=state.get("pipeline", []))
        return json.dumps(state, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


def handle_clear(args, **kwargs):
    """Close all kanban tasks for the current pipeline."""
    try:
        state = kb.scan_board()
        if state:
            kb.on_clear(state)
        retro = rt.get_retro()
        retro.log("pipeline_clear")
        rt.reset_retro()
        return json.dumps({"status": "ok"})
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


def handle_resume(args, **kwargs):
    """Scan board for an active pipeline. Returns state or null."""
    try:
        state = kb.scan_board()
        if state is None:
            return json.dumps(None)
        retro = rt.get_retro()
        retro.log(
            "pipeline_resume",
            category=state.get("category", ""),
            primary=state.get("primary", ""),
            pipeline_len=len(state.get("pipeline", [])),
            round=state.get("round", 0),
            agent_count=len(state.get("pipeline", [])),
        )
        return json.dumps(state, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


def handle_advance(args, **kwargs):
    """Mark agent complete, promote next. Returns updated state."""
    try:
        state = args["state"]
        agent = args["completed_agent"]
        state = kb.advance(state, agent)
        retro = rt.get_retro()
        retro.agent_done(
            agent,
            duration_s=args.get("duration_s", 0),
            tokens_response=args.get("tokens_response"),
            result=args.get("status", "ok"),
        )
        return json.dumps(state, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


# ── Agent context sections ──────────────────────────────────────────────────


AGENT_CONTEXT_FIELDS = {
    "finder": ["research"],
    "analyst": ["research"],
    "researcher": ["research"],
    "architect": ["research", "planning"],
    "planner": ["planning", "infrastructure"],
    "coder": ["implementation", "planning"],
    "fixer": ["implementation"],
    "refactorer": ["implementation"],
    "reviewer": ["implementation", "research"],
    "security": ["implementation", "research"],
    "integration": ["implementation", "documentation", "infrastructure"],
    "tester": ["implementation"],
    "debugger": ["implementation"],
    "documenter": ["implementation", "documentation"],
    "devops": ["infrastructure"],
    "optimizer": ["implementation"],
}


def _build_agent_prompt(agent_id: str, context: dict, request: str, category: str) -> dict:
    """Build a prompt for an agent, including only the context sections it needs.

    If no .prompt file exists for the agent, generates a default prompt
    from AGENT_CONTEXT_FIELDS.
    """
    agent_id = os.path.basename(agent_id)
    prompt_path = os.path.join(_get_plugin_dir(), "agents", f"{agent_id}.prompt")
    resolved = os.path.realpath(prompt_path)
    agents_dir = os.path.realpath(os.path.join(_get_plugin_dir(), "agents"))
    if not resolved.startswith(agents_dir):
        return {"error": f"Unknown agent: {agent_id}"}

    if os.path.exists(resolved):
        with open(resolved, "r", encoding="utf-8") as f:
            template = f.read()
    else:
        fields = AGENT_CONTEXT_FIELDS.get(agent_id, [])
        sections = ", ".join(fields) if fields else "full_context"
        template = (
            f"Ты — @{agent_id} в пайплайне.\n\n"
            f"## Задача\n{{request}}\n\n"
            f"## Контекст\n"
            f"Твои секции контекста: {sections}\n\n"
        )
        for field in fields:
            template += f"{{{field}_context}}\n\n"
        if not fields:
            template += "{full_context}\n\n"
        template += "Выполни свою задачу на основе контекста."
        rt.get_retro().log("default_prompt", agent=agent_id, sections=sections)

    request_esc = request.replace("{", "{{").replace("}", "}}")
    category_esc = category.replace("{", "{{").replace("}", "}}")

    fields = AGENT_CONTEXT_FIELDS.get(agent_id)
    if fields is None:
        fields = [
            "research",
            "planning",
            "implementation",
            "quality",
            "documentation",
            "infrastructure",
            "full_context",
        ]

    format_kwargs = {
        "request": request_esc,
        "category": category_esc,
    }
    for field in fields:
        if field == "full_context":
            format_kwargs["full_context"] = json.dumps(context, ensure_ascii=False, indent=2)
        else:
            field_name = f"{field}_context"
            format_kwargs[field_name] = json.dumps(
                context.get(field, {}), ensure_ascii=False, indent=2
            )

    try:
        formatted = template.format(**format_kwargs)
        return {"prompt": formatted}
    except KeyError as e:
        return {"error": f"Missing placeholder in prompt: {e}"}


def handle_prompt(args, **kwargs):
    try:
        agent_id = args["agent_id"]
        context = args.get("context", {})
        request = args.get("request", "")
        category = args.get("category", "")

        result = _build_agent_prompt(agent_id, context, request, category)
        if "error" in result:
            return json.dumps(result)
        return json.dumps(result, ensure_ascii=False)
    except KeyError as e:
        return json.dumps({"error": f"Missing placeholder: {e}"})
    except Exception as e:
        return json.dumps({"error": str(e), "traceback": traceback.format_exc()})


# ── Model config loader (hot-reload) ─────────────────────────────────────────


_MODEL_MAP_CACHE: dict[str, dict[str, str]] = {}
_CONFIG_MTIME: int = 0


def _load_model_map() -> dict[str, dict[str, str]]:
    """Load model map with hot-reload: checks config.yaml mtime (nanosecond) on each call."""
    from models import load_model_config

    config_path = os.path.join(_get_plugin_dir(), "config.yaml")
    try:
        stat = os.stat(config_path)
        current_mtime = stat.st_mtime_ns
    except OSError:
        current_mtime = 0

    global _CONFIG_MTIME, _MODEL_MAP_CACHE
    if current_mtime > _CONFIG_MTIME or not _MODEL_MAP_CACHE:
        _MODEL_MAP_CACHE = load_model_config()
        _CONFIG_MTIME = current_mtime
        logger.info("Loaded MODEL_MAP from config.yaml (%d agents)", len(_MODEL_MAP_CACHE))

    return _MODEL_MAP_CACHE


def get_model_map() -> dict[str, dict[str, str]]:
    """Get current model map (always fresh)."""
    return _load_model_map()


def handle_model(args, **kwargs):
    try:
        agent_id = args["agent_id"]
        result = get_model_map().get(agent_id)
        if result is None:
            return json.dumps({"error": f"Unknown agent: {agent_id}"})
        return json.dumps(result)
    except Exception as e:
        return json.dumps({"error": str(e)})


def handle_run_agent(args, **kwargs):
    """Build delegation package: prompt + routing + directive."""
    try:
        agent_id = args["agent_id"]
        state = args["state"]
        context_override = args.get("context")

        if "request" not in state:
            return json.dumps({"error": "State missing required field: request"})
        if "pipeline" not in state:
            return json.dumps({"error": "State missing required field: pipeline"})

        retro = rt.get_retro()

        agent_id = os.path.basename(agent_id)
        routing = get_model_map().get(agent_id)
        if routing is None:
            retro.log("error", agent=agent_id, error=f"Unknown agent: {agent_id}")
            return json.dumps({"error": f"Unknown agent: {agent_id}"})

        provider = routing["provider"]
        model = routing["model"]

        if provider == "delegate":
            directive = "delegate"
            tool_hint = "delegate_task"
        elif provider == "delegate_free":
            directive = "delegate_free"
            tool_hint = "delegate_task"
        else:
            directive = "direct"
            tool_hint = None

        retro.model_routing(
            agent_id, effective=f"{provider}/{model}", configured=f"{provider}/{model}"
        )

        ctx = context_override if context_override is not None else state.get("context", {})
        request = state.get("request", "")
        category = state.get("category", "")

        prompt_result = _build_agent_prompt(agent_id, ctx, request, category)
        if "error" in prompt_result:
            return json.dumps(prompt_result)
        prompt = prompt_result["prompt"]

        tokens_prompt = len(prompt) // 4
        retro.agent_start(
            agent_id,
            directive=directive,
            model=model,
            round=state.get("round", 0),
            tokens_prompt=tokens_prompt,
        )

        if directive == "direct":
            return json.dumps(
                {
                    "agent_id": agent_id,
                    "directive": directive,
                    "tool_hint": tool_hint,
                    "provider": provider,
                    "model": model,
                    "prompt": prompt,
                    "call_args": None,
                    "state": state,
                },
                ensure_ascii=False,
            )

        call_args = {
            "prompt": prompt,
            "provider": provider,
            "model": model,
            "description": f"Pipeline agent: {agent_id}",
        }

        return json.dumps(
            {
                "agent_id": agent_id,
                "directive": directive,
                "tool_hint": tool_hint,
                "provider": provider,
                "model": model,
                "prompt": prompt,
                "call_args": call_args,
                "state": state,
            },
            ensure_ascii=False,
        )

    except KeyError as e:
        return json.dumps({"error": f"Missing placeholder in prompt: {e}"})
    except Exception as e:
        return json.dumps({"error": str(e), "traceback": traceback.format_exc()})


def handle_ensemble_run(args, **kwargs):
    """Generate N candidate packages for ensemble execution."""
    try:
        state = args["state"]
        agent_id = args["agent_id"]
        n = args.get("n", 5)

        retro = rt.get_retro()

        if not should_use_ensemble(state, agent_id):
            retro.log("ensemble_disabled", agent=agent_id, reason=f"Round {state.get('round', 0)} > max")
            return json.dumps(
                {
                    "agent_id": agent_id,
                    "n": 1,
                    "ensemble": False,
                    "reason": "Ensemble disabled for this agent/round",
                    "candidates": [
                        {
                            "id": "single",
                            "task": state.get("request", ""),
                            "temperature": 0.7,
                            "instruction_extra": "Single pass",
                        }
                    ],
                },
                ensure_ascii=False,
            )

        candidates = ensemble_generate_candidates(state, agent_id, n)

        temps = [c.get("temperature", 0) for c in candidates]
        retro.ensemble_gen(agent_id, n=len(candidates), temperatures=temps)

        kb.create_ensemble_subtasks(state, agent_id, candidates)

        return json.dumps(
            {
                "agent_id": agent_id,
                "n": len(candidates),
                "ensemble": True,
                "candidates": candidates,
            },
            ensure_ascii=False,
        )
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


def handle_ensemble_judge(args, **kwargs):
    """Evaluate candidates and select best one."""
    try:
        request = args["request"]
        candidates = args["candidates"]
        judge_mode = args.get("judge_mode", "deterministic")

        config = read_ensemble_config()
        judge_cfg = config.get("judge", {}) if isinstance(config, dict) else {}
        result = ensemble_judge_candidates(request, candidates, judge_mode, judge_cfg)

        retro = rt.get_retro()
        retro.ensemble_judge(
            winner=result.get("winner_id", "?"),
            mode=result.get("mode", judge_mode),
            rationale=result.get("rationale", ""),
        )

        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


def handle_pipeline_command(raw_args: str) -> str:
    """Slash-command /pipeline — show kanban status.

    Usage: /pipeline [status|show|clear]
    """
    args = raw_args.strip().lower().split()
    cmd = args[0] if args else "status"

    return _render_pipeline_status(cmd)


def handle_pipeline_cli(args):
    """CLI command handler for 'hermes pipeline <subcommand>'.

    Receives argparse Namespace with pipeline_subcommand field.
    """
    cmd = getattr(args, "pipeline_subcommand", "status") or "status"
    result = _render_pipeline_status(cmd)
    print(result)


# ── Metrics hook ────────────────────────────────────────────────────────────


_PIPELINE_TOOL_COUNTERS: dict[str, int] = {}
"""tool_name → call count — обнуляется при рестарте плагина."""


def _on_pre_tool_call(tool_name: str, args: dict, task_id: str, **kwargs) -> None:
    """pre_tool_call hook: считает вызовы pipeline-инструментов.

    Регистрируется в __init__.py через ctx.register_hook('pre_tool_call', fn).
    """
    if tool_name.startswith("pipeline_") or tool_name.startswith("agent_"):
        count = _PIPELINE_TOOL_COUNTERS.get(tool_name, 0) + 1
        _PIPELINE_TOOL_COUNTERS[tool_name] = count


def get_pipeline_metrics() -> dict:
    """Return the current call counters.

    Exposed so /pipeline status может показать статистику.
    """
    return dict(_PIPELINE_TOOL_COUNTERS)


def _render_pipeline_status(cmd: str) -> str:
    """Shared rendering for both slash and CLI commands."""
    if cmd == "clear":
        state = kb.scan_board()
        if state:
            kb.on_clear(state)
            rt.reset_retro()
            return "✅ Pipeline board cleared"
        return "ℹ️ No active pipeline"

    if cmd in ("status", "show"):
        state = kb.scan_board()
        if state is None:
            return "ℹ️ No active pipeline"

        pipeline = state.get("pipeline", [])
        completed = state.get("completed", [])
        current_idx = state.get("current_idx", 0)
        category = state.get("category", "?")
        round_num = state.get("round", 0)

        current = pipeline[current_idx] if current_idx < len(pipeline) else "done"
        progress = f"{len(completed)}/{len(pipeline)}"

        lines = [
            f"🔷 Pipeline: {state.get('request', '?')[:60]}",
            f"  Category: {category}  Round: {round_num}  Progress: {progress}",
            f"  Current: @{current}",
            f"  Completed: {', '.join(completed) if completed else 'none'}",
            f"  Remaining: {', '.join(pipeline[current_idx:]) if current_idx < len(pipeline) else 'all done'}",
        ]
        return "\n".join(lines)

    return "Usage: /pipeline [status|show|clear]"


# ── Exports ──────────────────────────────────────────────────────────────────


__all__ = [
    "handle_classify",
    "handle_convergence",
    "handle_save",
    "handle_load",
    "handle_clear",
    "handle_resume",
    "handle_advance",
    "handle_prompt",
    "handle_model",
    "handle_run_agent",
    "handle_ensemble_run",
    "handle_ensemble_judge",
    "handle_pipeline_command",
    "handle_pipeline_cli",
    "get_model_map",
]
