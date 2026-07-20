"""
Pipeline Plugin v2.1 — Kanban-native multi-agent orchestration.

Variant C: state.json eliminated. kanban.db = single source of truth.
Board `pipeline` stores the entire pipeline lifecycle as a task tree.

Provides 10 tools:
  - pipeline_classify: classify request → category + agent list
  - pipeline_convergence: evaluate convergence (deterministic, no LLM)
  - pipeline_save: create/update kanban task tree (idempotent)
  - pipeline_load: reconstruct state from kanban board
  - pipeline_clear: close all kanban tasks (abort/cancel)
  - pipeline_resume: scan board for active pipeline (for restarts)
  - pipeline_advance: mark agent done, promote next
  - agent_prompt: build prompt for a specific agent
  - agent_model: get provider+model for a specific agent
  - pipeline_run_agent: build delegation package for an agent (10th, v2.1)

Key change from v1.x:
  - state.py removed → convergence logic in kanban.py
  - state.json removed → state in kanban.db (Hermes Kanban board)
  - After restart: pipeline_resume() scans board, no state.json needed

Key change from v2.0:
  - pipeline_run_agent added — delegation package pattern (agent→orchestrator bridge)
"""

import json
import logging
import os
import sys
import traceback

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
if PLUGIN_DIR not in sys.path:
    sys.path.insert(0, PLUGIN_DIR)

logger = logging.getLogger(__name__)

import classify
import kanban as kb
import retro as rt


# ── Import ensemble with retro logging ──────────────────────────────────────


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

# ── Tool schemas ──────────────────────────────────────────────────────────────

CLASSIFY_SCHEMA = {
    "name": "pipeline_classify",
    "description": "Classify a user request into a pipeline category and return the agent list.",
    "parameters": {
        "type": "object",
        "properties": {
            "request": {
                "type": "string",
                "description": "The user's request text",
            },
        },
        "required": ["request"],
    },
}

CONVERGENCE_SCHEMA = {
    "name": "pipeline_convergence",
    "description": "Evaluate pipeline convergence (deterministic, no LLM). Returns continue/converged/stuck/maxed_out based on round count, findings fingerprint, and severity counts. Findings are posted to the Kanban board as comments.",
    "parameters": {
        "type": "object",
        "properties": {
            "state": {
                "type": "object",
                "description": "Pipeline state dict (from pipeline_load or pipeline_resume). Must contain pipeline, kanban_parent_id, etc.",
            },
            "findings": {
                "type": "array",
                "description": "Current round findings (list of dicts with severity/file/category/description). Optional — omit to evaluate without new findings.",
                "items": {
                    "type": "object",
                    "properties": {
                        "severity": {"type": "string", "enum": ["P0", "P1", "P2"]},
                        "file": {"type": "string"},
                        "category": {"type": "string"},
                        "description": {"type": "string"},
                    },
                    "required": ["severity", "file", "category"],
                },
            },
        },
        "required": ["state"],
    },
}

SAVE_SCHEMA = {
    "name": "pipeline_save",
    "description": "Create/update the kanban task tree for a pipeline run. Idempotent — if the parent task already exists (by idempotency key), subsequent calls update existing tasks without duplication. Returns the state dict with kanban_parent_id and kanban_task_ids populated.",
    "parameters": {
        "type": "object",
        "properties": {
            "state": {
                "type": "object",
                "description": "Pipeline state with request, category, pipeline fields. On first call, creates the full task tree. On subsequent calls, returns existing tree.",
                "properties": {
                    "request": {"type": "string"},
                    "category": {"type": "string"},
                    "pipeline": {"type": "array", "items": {"type": "string"}},
                    "current_idx": {"type": "integer"},
                    "completed": {"type": "array", "items": {"type": "string"}},
                    "context": {"type": "object"},
                    "checkpoints": {"type": "object"},
                    "status": {"type": "string", "enum": ["running", "paused", "done"]},
                },
                "required": ["request", "category", "pipeline", "status"],
            },
        },
        "required": ["state"],
    },
}

LOAD_SCHEMA = {
    "name": "pipeline_load",
    "description": "Scan the kanban board for the current pipeline state. Returns the reconstructed state dict for the active (non-completed, non-cancelled) pipeline run, or None if no active pipeline is found.",
    "parameters": {
        "type": "object",
        "properties": {},
        "required": [],
    },
}

CLEAR_SCHEMA = {
    "name": "pipeline_clear",
    "description": "Close all kanban tasks for the current pipeline run (cancels/aborts).",
    "parameters": {
        "type": "object",
        "properties": {},
        "required": [],
    },
}

RESUME_SCHEMA = {
    "name": "pipeline_resume",
    "description": "Scan the pipeline board for an active (non-completed) pipeline run. Returns reconstructed state dict or null if idle. Use this after agent restart to pick up where you left off — finds ready/todo/running tasks and reconstructs pipeline, current_idx, completed, etc.",
    "parameters": {
        "type": "object",
        "properties": {},
        "required": [],
    },
}

ADVANCE_SCHEMA = {
    "name": "pipeline_advance",
    "description": "Mark an agent task as complete and promote the next agent in the pipeline. Returns updated state dict with current_idx advanced.",
    "parameters": {
        "type": "object",
        "properties": {
            "state": {
                "type": "object",
                "description": "Current pipeline state (from pipeline_load/resume).",
            },
            "completed_agent": {
                "type": "string",
                "description": "Agent id that just completed (e.g. 'finder', 'analyst', 'coder').",
            },
        },
        "required": ["state", "completed_agent"],
    },
}

PROMPT_SCHEMA = {
    "name": "agent_prompt",
    "description": "Build a prompt for a specific pipeline agent, injecting context.",
    "parameters": {
        "type": "object",
        "properties": {
            "agent_id": {
                "type": "string",
                "description": "Agent identifier: architect, reviewer, security, researcher",
            },
            "context": {
                "type": "object",
                "description": "Context object with research, planning, implementation, etc.",
            },
            "request": {
                "type": "string",
                "description": "Original user request",
            },
            "category": {
                "type": "string",
                "description": "Pipeline category",
            },
        },
        "required": ["agent_id", "context"],
    },
}

MODEL_SCHEMA = {
    "name": "agent_model",
    "description": "Get provider and model for a specific agent.",
    "parameters": {
        "type": "object",
        "properties": {
            "agent_id": {
                "type": "string",
                "description": "Agent identifier",
            },
        },
        "required": ["agent_id"],
    },
}

RUN_AGENT_SCHEMA = {
    "name": "pipeline_run_agent",
    "description": (
        "Build a delegation package for running a pipeline agent. "
        "The orchestrator reads the response and calls delegate_task (for Pro agents) "
        "or executes the prompt directly (for Flash agents). "
        "Returns {agent_id, directive, tool_hint, provider, model, prompt, call_args, state}."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "state": {
                "type": "object",
                "description": "Current pipeline state (from pipeline_load/resume).",
            },
            "agent_id": {
                "type": "string",
                "description": "Agent to run: architect, reviewer, security, coder, etc.",
            },
            "context": {
                "type": "object",
                "description": "Optional context override. Uses state.context if omitted.",
            },
        },
        "required": ["state", "agent_id"],
    },
}


# ── Ensemble tool schemas ─────────────────────────────────────────────────────


ENSEMBLE_RUN_SCHEMA = {
    "name": "pipeline_ensemble_run",
    "description": (
        "Generate N candidate task packages for Best-of-N ensemble execution. "
        "Returns list of candidate packages with varied temperature/instructions. "
        "Orchestrator runs delegate_task for each, then calls pipeline_ensemble_judge."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "state": {
                "type": "object",
                "description": "Current pipeline state",
            },
            "agent_id": {
                "type": "string",
                "description": "Agent to run in ensemble mode (e.g. 'coder')",
            },
            "n": {
                "type": "integer",
                "description": "Number of candidates (default: 5, max: 10)",
                "default": 5,
                "minimum": 2,
                "maximum": 10,
            },
        },
        "required": ["state", "agent_id"],
    },
}


ENSEMBLE_JUDGE_SCHEMA = {
    "name": "pipeline_ensemble_judge",
    "description": (
        "Evaluate N candidate results and select the best one. "
        "Returns winner id, rationale, and all candidate scores."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "request": {
                "type": "string",
                "description": "Original task/request",
            },
            "candidates": {
                "type": "array",
                "description": "Array of candidate results with id and output",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "output": {"type": "string"},
                        "temperature": {"type": "number"},
                    },
                },
            },
        },
        "required": ["request", "candidates"],
    },
}


# ── Handlers ──────────────────────────────────────────────────────────────────


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
        result = kb.evaluate_convergence(state, findings)
        kb.on_convergence(state, result)

        # Retro log convergence
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

        # Auto-analysis on maxed_out/stuck
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

        # Wire retro with the new run_id
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
        retro.log("agent_done", agent=agent)
        return json.dumps(state, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


# ── Agent context sections: какие секции контекста нужны каждому агенту ──
# Вместо полного контекста передаём только релевантные секции.
# full_context убран — integration.prompt переписан на конкретные секции.
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
    prompt_path = os.path.join(PLUGIN_DIR, "agents", f"{agent_id}.prompt")
    resolved = os.path.realpath(prompt_path)
    agents_dir = os.path.realpath(os.path.join(PLUGIN_DIR, "agents"))
    if not resolved.startswith(agents_dir):
        return {"error": f"Unknown agent: {agent_id}"}

    if os.path.exists(resolved):
        with open(resolved, "r", encoding="utf-8") as f:
            template = f.read()
    else:
        # Generate default prompt from AGENT_CONTEXT_FIELDS
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

    # Build only the context sections this agent actually needs
    # Unknown agents (not in AGENT_CONTEXT_FIELDS) get all sections for backward compat
    fields = AGENT_CONTEXT_FIELDS.get(agent_id)
    if fields is None:
        # Fallback: render all 6 context sections + full_context for unknown agents
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
    """Load model map with hot-reload: checks config.yaml mtime (nanosecond) on each call.

    Uses os.stat().st_mtime_ns for nanosecond-precision mtime comparison,
    avoiding the 1-second granularity issue of os.path.getmtime() on
    overlayfs/Docker filesystems.
    """
    from models import load_model_config

    config_path = os.path.join(PLUGIN_DIR, "config.yaml")
    try:
        stat = os.stat(config_path)
        current_mtime = stat.st_mtime_ns  # nanosecond precision
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
    """Build delegation package: prompt + routing + directive.

    Returns {agent_id, directive, tool_hint, provider, model, prompt, call_args, state}.
    Orchestrator reads call_args and calls delegate_task(**call_args) for Pro agents,
    or uses prompt directly for Flash agents.
    """
    try:
        agent_id = args["agent_id"]
        state = args["state"]
        context_override = args.get("context")

        # 1. Validate state
        if "request" not in state:
            return json.dumps({"error": "State missing required field: request"})
        if "pipeline" not in state:
            return json.dumps({"error": "State missing required field: pipeline"})

        retro = rt.get_retro()

        # 2. Validate agent_id (path traversal guard — same as handle_prompt)
        agent_id = os.path.basename(agent_id)
        routing = get_model_map().get(agent_id)
        if routing is None:
            retro.log("error", agent=agent_id, error=f"Unknown agent: {agent_id}")
            return json.dumps({"error": f"Unknown agent: {agent_id}"})

        # 3. Determine directive first (used by logging below)
        provider = routing["provider"]
        model = routing["model"]

        if provider == "delegate":
            directive = "delegate"
            tool_hint = "delegate_task"
        elif provider == "delegate_free":
            directive = "delegate_free"
            tool_hint = "delegate_task"
        else:  # "direct"
            directive = "direct"
            tool_hint = None

        # 4. Log model routing & agent start
        retro.model_routing(
            agent_id, effective=f"{provider}/{model}", configured=f"{provider}/{model}"
        )

        ctx = context_override if context_override is not None else state.get("context", {})
        tokens_prompt = len(json.dumps(ctx, ensure_ascii=False)) // 4  # rough estimate
        retro.agent_start(
            agent_id,
            directive=directive,
            model=model,
            round=state.get("round", 0),
            tokens_prompt=tokens_prompt,
        )

        # 5. Build prompt for ALL agents (Flash + Pro)
        ctx = context_override if context_override is not None else state.get("context", {})
        request = state.get("request", "")
        category = state.get("category", "")

        # 5a. Build prompt via shared function (selective context, no full_context)
        prompt_result = _build_agent_prompt(agent_id, ctx, request, category)
        if "error" in prompt_result:
            return json.dumps(prompt_result)
        prompt = prompt_result["prompt"]

        if directive == "direct":
            # Flash agents: return package with prompt
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

        # 6. Build call_args for delegation agents
        call_args = {
            "prompt": prompt,
            "provider": provider,
            "model": model,
            "description": f"Pipeline agent: {agent_id}",
        }

        # 7. Return delegation package
        return json.dumps(
            {
                "agent_id": agent_id,
                "directive": directive,
                "tool_hint": tool_hint,
                "provider": provider,
                "model": model,
                "prompt": prompt,
                "call_args": call_args,
                "state": state,  # pass-through for pipeline_advance
            },
            ensure_ascii=False,
        )

    except KeyError as e:
        return json.dumps({"error": f"Missing placeholder in prompt: {e}"})
    except Exception as e:
        return json.dumps({"error": str(e), "traceback": traceback.format_exc()})


def handle_ensemble_run(args, **kwargs):
    """Generate N candidate packages for ensemble execution.

    Checks config: if ensemble disabled or round > max, returns single.
    Creates kanban sub-tasks for each candidate.
    """
    try:
        state = args["state"]
        agent_id = args["agent_id"]
        n = args.get("n", 5)

        retro = rt.get_retro()

        # Check if ensemble should be used
        if not should_use_ensemble(state, agent_id):
            retro.log(
                "ensemble_disabled", agent=agent_id, reason=f"Round {state.get('round', 0)} > max"
            )
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

        # Retro log
        temps = [c.get("temperature", 0) for c in candidates]
        retro.ensemble_gen(agent_id, n=len(candidates), temperatures=temps)

        # Create kanban sub-tasks for visibility
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
    """Evaluate candidates and select best one.

    If mode=llm and judge_prompt available, returns judge_call_args
    for the orchestrator to run delegate_task and get real LLM evaluation.
    Otherwise uses deterministic fallback.
    """
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


# ── Registration ──────────────────────────────────────────────────────────────


def register(ctx):
    for name, schema, handler in [
        ("pipeline_classify", CLASSIFY_SCHEMA, handle_classify),
        ("pipeline_convergence", CONVERGENCE_SCHEMA, handle_convergence),
        ("pipeline_save", SAVE_SCHEMA, handle_save),
        ("pipeline_load", LOAD_SCHEMA, handle_load),
        ("pipeline_clear", CLEAR_SCHEMA, handle_clear),
        ("pipeline_resume", RESUME_SCHEMA, handle_resume),
        ("pipeline_advance", ADVANCE_SCHEMA, handle_advance),
        ("agent_prompt", PROMPT_SCHEMA, handle_prompt),
        ("agent_model", MODEL_SCHEMA, handle_model),
        ("pipeline_run_agent", RUN_AGENT_SCHEMA, handle_run_agent),
        ("pipeline_ensemble_run", ENSEMBLE_RUN_SCHEMA, handle_ensemble_run),
        ("pipeline_ensemble_judge", ENSEMBLE_JUDGE_SCHEMA, handle_ensemble_judge),
    ]:
        ctx.register_tool(
            name=name,
            toolset="pipeline",
            schema=schema,
            handler=handler,
        )
