"""
Pipeline Plugin v3.7.2 — Kanban-native multi-agent orchestration.
Handlers extracted to handlers/ module (was 892 lines in one file).

Variant C: state.json eliminated. kanban.db = single source of truth.
Board `pipeline` stores the entire pipeline lifecycle as a task tree.

Provides 12 tools:
  - pipeline_classify: classify request → category + agent list
  - pipeline_convergence: evaluate convergence (deterministic, no LLM)
  - pipeline_save: create/update kanban task tree (idempotent)
  - pipeline_load: reconstruct state from kanban board
  - pipeline_clear: close all kanban tasks (abort/cancel)
  - pipeline_resume: scan board for active pipeline (for restarts)
  - pipeline_advance: mark agent done, promote next
  - agent_prompt: build prompt for a specific agent
  - agent_model: get provider+model for a specific agent
  - pipeline_run_agent: build delegation package for an agent
  - pipeline_ensemble_run: generate N candidate packages
  - pipeline_ensemble_judge: evaluate N candidates and select best
"""

import logging
import os
import sys
from pathlib import Path

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
if PLUGIN_DIR not in sys.path:
    sys.path.insert(0, PLUGIN_DIR)

logger = logging.getLogger(__name__)

from handlers import (
    handle_advance,
    handle_classify,
    handle_clear,
    handle_convergence,
    handle_ensemble_judge,
    handle_ensemble_run,
    handle_load,
    handle_model,
    handle_pipeline_cli,
    handle_pipeline_command,
    handle_prompt,
    handle_resume,
    handle_run_agent,
    handle_save,
)


def _ensemble_enabled() -> bool:
    """check_fn: скрыть ensemble инструменты, если ensemble выключен в config.yaml."""
    try:
        from ensemble import read_ensemble_config
        config = read_ensemble_config()
        return bool(config.get("enabled", True))
    except Exception:
        return True  # fail open — если конфиг не читается, показываем инструменты


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
    "description": (
        "Evaluate pipeline convergence (deterministic, no LLM). "
        "Returns continue/converged/stuck/maxed_out based on round count, "
        "findings fingerprint, and severity counts. "
        "Findings are posted to the Kanban board as comments."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "state": {
                "type": "object",
                "description": "Pipeline state dict (from pipeline_load or pipeline_resume). "
                               "Must contain pipeline, kanban_parent_id, etc.",
            },
            "findings": {
                "type": "array",
                "description": "Current round findings (list of dicts with severity/file/category/description). "
                               "Optional — omit to evaluate without new findings.",
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
    "description": (
        "Create/update the kanban task tree for a pipeline run. Idempotent — "
        "if the parent task already exists (by idempotency key), subsequent calls "
        "update existing tasks without duplication. Returns the state dict with "
        "kanban_parent_id and kanban_task_ids populated."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "state": {
                "type": "object",
                "description": "Pipeline state with request, category, pipeline fields. "
                               "On first call, creates the full task tree. On subsequent calls, returns existing tree.",
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
    "description": (
        "Scan the kanban board for the current pipeline state. Returns the "
        "reconstructed state dict for the active (non-completed, non-cancelled) "
        "pipeline run, or None if no active pipeline is found."
    ),
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
    "description": (
        "Scan the pipeline board for an active (non-completed) pipeline run. "
        "Returns reconstructed state dict or null if idle. Use this after agent "
        "restart to pick up where you left off — finds ready/todo/running tasks "
        "and reconstructs pipeline, current_idx, completed, etc."
    ),
    "parameters": {
        "type": "object",
        "properties": {},
        "required": [],
    },
}

ADVANCE_SCHEMA = {
    "name": "pipeline_advance",
    "description": (
        "Mark an agent task as complete and promote the next agent in the pipeline. "
        "Returns updated state dict with current_idx advanced."
    ),
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
            "duration_s": {
                "type": "number",
                "description": "Optional agent execution time in seconds.",
            },
            "tokens_response": {
                "type": "integer",
                "description": "Optional response token count.",
            },
            "status": {
                "type": "string",
                "description": "Optional completion status (ok, error, skipped).",
                "enum": ["ok", "error", "skipped"],
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


# ── Registration ──────────────────────────────────────────────────────────────


def register(ctx):
    # Store ctx for slash-command dispatch_tool
    from . import _ctx as plugin_ctx
    plugin_ctx.set_ctx(ctx)

    # Register auxiliary task so classify model is independently configurable
    try:
        ctx.register_auxiliary_task(
            key="pipeline_classify",
            display_name="Pipeline classifier",
            description="LLM-based request classifier for pipeline routing",
            defaults={"provider": "auto", "model": "", "timeout": 30},
        )
    except Exception:
        logger.info("register_auxiliary_task not available — skipping (Hermes pre-3.8?)")
    # Register bundled skills via ctx.register_skill() (Hermes plugin SDK)
    skills_dir = Path(__file__).parent / "skill"
    if skills_dir.is_dir():
        for child in sorted(skills_dir.iterdir()):
            skill_md = child / "SKILL.md"
            if child.is_dir() and skill_md.exists():
                try:
                    ctx.register_skill(child.name, skill_md)
                except Exception:
                    logger.warning("Could not register skill %s", child.name)

    for name, schema, handler, check_fn in [
        ("pipeline_classify", CLASSIFY_SCHEMA, handle_classify, None),
        ("pipeline_convergence", CONVERGENCE_SCHEMA, handle_convergence, None),
        ("pipeline_save", SAVE_SCHEMA, handle_save, None),
        ("pipeline_load", LOAD_SCHEMA, handle_load, None),
        ("pipeline_clear", CLEAR_SCHEMA, handle_clear, None),
        ("pipeline_resume", RESUME_SCHEMA, handle_resume, None),
        ("pipeline_advance", ADVANCE_SCHEMA, handle_advance, None),
        ("agent_prompt", PROMPT_SCHEMA, handle_prompt, None),
        ("agent_model", MODEL_SCHEMA, handle_model, None),
        ("pipeline_run_agent", RUN_AGENT_SCHEMA, handle_run_agent, None),
        ("pipeline_ensemble_run", ENSEMBLE_RUN_SCHEMA, handle_ensemble_run, _ensemble_enabled),
        ("pipeline_ensemble_judge", ENSEMBLE_JUDGE_SCHEMA, handle_ensemble_judge, _ensemble_enabled),
    ]:
        ctx.register_tool(
            name=name,
            toolset="pipeline",
            schema=schema,
            handler=handler,
            check_fn=check_fn,
        )

    # Register slash-commands (in-session, works in CLI + gateway)
    ctx.register_command(
        "pipeline",
        handler=handle_pipeline_command,
        description="Show pipeline kanban status. Usage: /pipeline [status|show|clear]",
        args_hint="[status|show|clear]",
    )

    # Register CLI command (hermes pipeline <subcommand>)
    def _setup_pipeline_argparse(subparser):
        subs = subparser.add_subparsers(dest="pipeline_subcommand")
        subs.add_parser("status", help="Show pipeline kanban status")
        subs.add_parser("show", help="Show pipeline kanban status (alias)")
        subs.add_parser("clear", help="Clear active pipeline board")
        subparser.set_defaults(func=handle_pipeline_cli)

    ctx.register_cli_command(
        name="pipeline",
        help="Pipeline plugin commands — status, show, clear",
        setup_fn=_setup_pipeline_argparse,
        handler_fn=handle_pipeline_cli,
    )

    # Register metrics hook — counts pipeline_* and agent_* calls
    from handlers import _on_pre_tool_call
    ctx.register_hook("pre_tool_call", _on_pre_tool_call)
