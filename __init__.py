"""
Pipeline Plugin — multi-agent orchestration for Hermes Agent.

Provides 6 tools:
  - pipeline_classify: classify request → category + pipeline
  - pipeline_save: persist pipeline state to disk
  - pipeline_load: load persisted pipeline state
  - pipeline_clear: remove persisted pipeline state
  - agent_prompt: build prompt for a specific agent
  - agent_model: get provider+model for a specific agent
"""

import json
import os
import sys
import traceback

# Absolute imports — works both as stand-alone and as Hermes plugin
PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
if PLUGIN_DIR not in sys.path:
    sys.path.insert(0, PLUGIN_DIR)

import classify
import state as pstate

# ── Tool schemas ─────────────────────────────────────────────────────────────┐

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

SAVE_SCHEMA = {
    "name": "pipeline_save",
    "description": "Save pipeline state to disk (overwrites previous state).",
    "parameters": {
        "type": "object",
        "properties": {
            "state": {
                "type": "object",
                "description": "Complete pipeline state object",
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
                "required": ["request", "category", "pipeline", "current_idx", "completed", "context", "checkpoints", "status"],
            },
        },
        "required": ["state"],
    },
}

LOAD_SCHEMA = {
    "name": "pipeline_load",
    "description": "Load the saved pipeline state from disk. Returns null if none exists.",
    "parameters": {
        "type": "object",
        "properties": {},
        "required": [],
    },
}

CLEAR_SCHEMA = {
    "name": "pipeline_clear",
    "description": "Delete saved pipeline state from disk.",
    "parameters": {
        "type": "object",
        "properties": {},
        "required": [],
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

# ── Handlers ─────────────────────────────────────────────────────────────────┘


def handle_classify(args, **kwargs):
    try:
        request = args["request"]
        result = classify.classify(request)
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e), "traceback": traceback.format_exc()})


def handle_save(args, **kwargs):
    try:
        state = args["state"]
        pstate.save(state)
        return json.dumps({"status": "ok"})
    except Exception as e:
        return json.dumps({"error": str(e)})


def handle_load(args, **kwargs):
    try:
        state = pstate.load()
        if state is None:
            return json.dumps(None)
        return json.dumps(state, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)})


def handle_clear(args, **kwargs):
    try:
        pstate.clear()
        return json.dumps({"status": "ok"})
    except Exception as e:
        return json.dumps({"error": str(e)})


def handle_prompt(args, **kwargs):
    try:
        agent_id = args["agent_id"]
        context = args.get("context", {})
        request = args.get("request", "")
        category = args.get("category", "")

        # Safe path resolution: prevent path traversal
        agent_id = os.path.basename(agent_id)  # strip any dir components
        prompt_path = os.path.join(PLUGIN_DIR, "agents", f"{agent_id}.prompt")

        # Resolve once, open on resolved path (avoids TOCTOU)
        resolved = os.path.realpath(prompt_path)
        agents_dir = os.path.realpath(os.path.join(PLUGIN_DIR, "agents"))

        # Verify the resolved path is under agents/ — single check, single open
        if not resolved.startswith(agents_dir):
            return json.dumps({"error": f"Unknown agent: {agent_id}"})

        with open(resolved, "r", encoding="utf-8") as f:
            template = f.read()

        # Escape literal braces in user-controlled strings to prevent KeyError
        request = request.replace("{", "{{").replace("}", "}}")
        category = category.replace("{", "{{").replace("}", "}}")

        formatted = template.format(
            request=request,
            category=category,
            research_context=json.dumps(context.get("research", {}), ensure_ascii=False, indent=2),
            planning_context=json.dumps(context.get("planning", {}), ensure_ascii=False, indent=2),
            implementation_context=json.dumps(context.get("implementation", {}), ensure_ascii=False, indent=2),
            quality_context=json.dumps(context.get("quality", {}), ensure_ascii=False, indent=2),
            documentation_context=json.dumps(context.get("documentation", {}), ensure_ascii=False, indent=2),
            infrastructure_context=json.dumps(context.get("infrastructure", {}), ensure_ascii=False, indent=2),
            full_context=json.dumps(context, ensure_ascii=False, indent=2),
        )

        return json.dumps({"prompt": formatted}, ensure_ascii=False)
    except KeyError as e:
        return json.dumps({"error": f"Missing placeholder in prompt template: {e}"})
    except Exception as e:
        return json.dumps({"error": str(e), "traceback": traceback.format_exc()})


MODEL_MAP = {
    # Direct (agent does these itself with DeepSeek V4 Flash)
    "finder":      {"provider": "direct", "model": "deepseek-v4-flash"},
    "analyst":     {"provider": "direct", "model": "deepseek-v4-flash"},
    "planner":     {"provider": "direct", "model": "deepseek-v4-flash"},
    "coder":       {"provider": "direct", "model": "deepseek-v4-flash"},
    "editor":      {"provider": "direct", "model": "deepseek-v4-flash"},
    "fixer":       {"provider": "direct", "model": "deepseek-v4-flash"},
    "refactorer":  {"provider": "direct", "model": "deepseek-v4-flash"},
    "tester":      {"provider": "direct", "model": "deepseek-v4-flash"},
    "debugger":    {"provider": "direct", "model": "deepseek-v4-flash"},
    "documenter":  {"provider": "direct", "model": "deepseek-v4-flash"},
    "devops":      {"provider": "direct", "model": "deepseek-v4-flash"},
    "optimizer":   {"provider": "direct", "model": "deepseek-v4-flash"},
    # delegate_task (auto DeepSeek V4 Pro via user's delegation setting)
    "architect":   {"provider": "delegate", "model": "deepseek-v4-pro"},
    "reviewer":    {"provider": "delegate", "model": "deepseek-v4-pro"},
    "security":    {"provider": "delegate", "model": "deepseek-v4-pro"},
    # delegate_task with OpenRouter free
    "researcher":  {"provider": "delegate_free", "model": "openrouter/free"},
    "commenter":   {"provider": "delegate_free", "model": "openrouter/free"},
}


def handle_model(args, **kwargs):
    try:
        agent_id = args["agent_id"]
        result = MODEL_MAP.get(agent_id)
        if result is None:
            return json.dumps({"error": f"Unknown agent: {agent_id}"})
        return json.dumps(result)
    except Exception as e:
        return json.dumps({"error": str(e)})


# ── Registration ─────────────────────────────────────────────────────────────┘


def register(ctx):
    ctx.register_tool(
        name="pipeline_classify",
        toolset="pipeline",
        schema=CLASSIFY_SCHEMA,
        handler=handle_classify,
    )
    ctx.register_tool(
        name="pipeline_save",
        toolset="pipeline",
        schema=SAVE_SCHEMA,
        handler=handle_save,
    )
    ctx.register_tool(
        name="pipeline_load",
        toolset="pipeline",
        schema=LOAD_SCHEMA,
        handler=handle_load,
    )
    ctx.register_tool(
        name="pipeline_clear",
        toolset="pipeline",
        schema=CLEAR_SCHEMA,
        handler=handle_clear,
    )
    ctx.register_tool(
        name="agent_prompt",
        toolset="pipeline",
        schema=PROMPT_SCHEMA,
        handler=handle_prompt,
    )
    ctx.register_tool(
        name="agent_model",
        toolset="pipeline",
        schema=MODEL_SCHEMA,
        handler=handle_model,
    )
