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
import os
import sys
import traceback

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
if PLUGIN_DIR not in sys.path:
    sys.path.insert(0, PLUGIN_DIR)

import classify
import kanban as kb

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


# ── Handlers ──────────────────────────────────────────────────────────────────


def handle_classify(args, **kwargs):
    try:
        request = args["request"]
        result = classify.classify(request)
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e), "traceback": traceback.format_exc()})


def handle_convergence(args, **kwargs):
    """Evaluate convergence. Findings posted to kanban board state in-memory."""
    try:
        state = args["state"]
        findings = args.get("findings")
        if findings is None and not state.get("findings"):
            return json.dumps({
                "decision": "unknown",
                "reason": "No findings — cannot evaluate",
                "round": state.get("round", 0),
            })
        result = kb.evaluate_convergence(state, findings)
        kb.on_convergence(state, result)
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e), "traceback": traceback.format_exc()},
                          ensure_ascii=False)


def handle_save(args, **kwargs):
    """Create/update kanban task tree. Idempotent."""
    try:
        state = args["state"]
        state = kb.create_task_tree(state)
        return json.dumps({
            "status": "ok",
            "kanban_parent_id": state.get("kanban_parent_id"),
            "kanban_task_ids": state.get("kanban_task_ids", {}),
        }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


def handle_load(args, **kwargs):
    """Scan kanban board for active pipeline state."""
    try:
        state = kb.scan_board()
        if state is None:
            return json.dumps(None)
        return json.dumps(state, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


def handle_clear(args, **kwargs):
    """Close all kanban tasks for the current pipeline."""
    try:
        state = kb.scan_board()
        if state:
            kb.on_clear(state)
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
        return json.dumps(state, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


# ── Agent context sections: какие секции контекста нужны каждому агенту ──
# Вместо полного контекста передаём только релевантные секции.
# full_context убран — integration.prompt переписан на конкретные секции.
AGENT_CONTEXT_FIELDS = {
    "finder":       ["research"],
    "analyst":      ["research"],
    "researcher":   ["research"],
    "architect":    ["research", "planning"],
    "planner":      ["planning", "infrastructure"],
    "coder":        ["implementation", "planning"],
    "editor":       ["implementation", "planning"],
    "fixer":        ["implementation"],
    "refactorer":   ["implementation"],
    "reviewer":     ["implementation", "research"],
    "security":     ["implementation", "research"],
    "integration":  ["implementation", "documentation", "infrastructure"],
    "tester":       ["implementation"],
    "debugger":     ["implementation"],
    "documenter":   ["implementation", "documentation"],
    "devops":       ["infrastructure"],
    "optimizer":    ["implementation"],
}


def _build_agent_prompt(agent_id: str, context: dict, request: str, category: str) -> dict:
    """Build a prompt for an agent, including only the context sections it needs."""
    import os

    agent_id = os.path.basename(agent_id)
    prompt_path = os.path.join(PLUGIN_DIR, "agents", f"{agent_id}.prompt")
    resolved = os.path.realpath(prompt_path)
    agents_dir = os.path.realpath(os.path.join(PLUGIN_DIR, "agents"))
    if not resolved.startswith(agents_dir):
        return {"error": f"Unknown agent: {agent_id}"}

    with open(resolved, "r", encoding="utf-8") as f:
        template = f.read()

    request_esc = request.replace("{", "{{").replace("}", "}}")
    category_esc = category.replace("{", "{{").replace("}", "}}")

    # Build only the context sections this agent actually needs
    # Unknown agents (not in AGENT_CONTEXT_FIELDS) get all sections for backward compat
    fields = AGENT_CONTEXT_FIELDS.get(agent_id)
    if fields is None:
        # Fallback: render all 6 context sections + full_context for unknown agents
        fields = ["research", "planning", "implementation", "quality", "documentation", "infrastructure",
                   "full_context"]

    format_kwargs = {
        "request": request_esc,
        "category": category_esc,
    }
    for field in fields:
        if field == "full_context":
            format_kwargs["full_context"] = json.dumps(context, ensure_ascii=False, indent=2)
        else:
            field_name = f"{field}_context"
            format_kwargs[field_name] = json.dumps(context.get(field, {}), ensure_ascii=False, indent=2)

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


try:
    from .models import load_model_config
except ImportError:
    from models import load_model_config  # noqa: F811

MODEL_MAP = load_model_config()


def handle_model(args, **kwargs):
    try:
        agent_id = args["agent_id"]
        result = MODEL_MAP.get(agent_id)
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

        # 2. Validate agent_id (path traversal guard — same as handle_prompt)
        agent_id = os.path.basename(agent_id)
        routing = MODEL_MAP.get(agent_id)
        if routing is None:
            return json.dumps({"error": f"Unknown agent: {agent_id}"})

        # 3. Determine directive
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
            # Flash agents: return minimal package without prompt file
            return json.dumps({
                "agent_id": agent_id,
                "directive": directive,
                "tool_hint": tool_hint,
                "provider": provider,
                "model": model,
                "prompt": None,
                "call_args": None,
                "state": state,
            }, ensure_ascii=False)

        # 4. Resolve context (delegation agents only)
        ctx = context_override if context_override is not None else state.get("context", {})
        request = state.get("request", "")
        category = state.get("category", "")

        # 5. Build prompt via shared function (selective context, no full_context)
        prompt_result = _build_agent_prompt(agent_id, ctx, request, category)
        if "error" in prompt_result:
            return json.dumps(prompt_result)
        prompt = prompt_result["prompt"]

        # 6. Build call_args for delegation agents
        call_args = {
            "prompt": prompt,
            "provider": provider,
            "model": model,
            "description": f"Pipeline agent: {agent_id}",
        }

        # 7. Return delegation package
        return json.dumps({
            "agent_id": agent_id,
            "directive": directive,
            "tool_hint": tool_hint,
            "provider": provider,
            "model": model,
            "prompt": prompt,
            "call_args": call_args,
            "state": state,  # pass-through for pipeline_advance
        }, ensure_ascii=False)

    except KeyError as e:
        return json.dumps({"error": f"Missing placeholder in prompt: {e}"})
    except Exception as e:
        return json.dumps({"error": str(e), "traceback": traceback.format_exc()})


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
        ("pipeline_run_agent", RUN_AGENT_SCHEMA, handle_run_agent),  # ← NEW 10th
    ]:
        ctx.register_tool(
            name=name,
            toolset="pipeline",
            schema=schema,
            handler=handler,
        )
