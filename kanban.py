"""
Kanban integration for Pipeline Plugin.

Automatically creates/updates Hermes Kanban tasks for pipeline runs.
Uses `hermes kanban` CLI via subprocess.

Board: pipeline (created once via `hermes kanban boards create pipeline`)
"""

import json
import logging
import subprocess
from typing import Any

logger = logging.getLogger(__name__)

BOARD = "pipeline"
KANBAN_TIMEOUT = 15  # seconds for each subprocess call

# ── Helpers ──────────────────────────────────────────────────────────────────┘


def _run_kanban(*args: str) -> dict[str, Any]:
    """Run ``hermes kanban --board <BOARD> <args>`` and return output.

    Tries JSON parse first, falls back to text dict.
    Returns {} on any error (never raises).
    """
    cmd = ["hermes", "kanban", "--board", BOARD]
    cmd.extend(args)
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=KANBAN_TIMEOUT,
        )
        if result.returncode != 0:
            stderr = result.stderr.strip()[:200]
            logger.warning(
                "kanban error (exit %d): %s", result.returncode, stderr
            )
            return {}
        out = result.stdout.strip()
        if not out:
            return {}
        # Try JSON first
        try:
            return json.loads(out)
        except json.JSONDecodeError:
            pass
        return {"_text": out}
    except subprocess.TimeoutExpired:
        logger.warning("kanban command timed out (>{KANBAN_TIMEOUT}s)")
        return {}
    except FileNotFoundError:
        logger.warning(
            "hermes binary not found in PATH — kanban integration disabled"
        )
        return {}
    except OSError as exc:
        logger.warning("kanban subprocess error: %s", exc)
        return {}


# ── Public API ───────────────────────────────────────────────────────────────┘


def create_task(
    title: str,
    body: str = "",
    idempotency_key: str = "",
) -> str | None:
    """Create a task on the pipeline board.

    Uses ``--idempotency-key`` when provided so restart doesn't duplicate.
    Returns the task ID (string) or None on failure.
    """
    cmd: list[str] = [
        "create",
        "--body",
        body,
        "--priority",
        "1",
        "--json",
    ]
    if idempotency_key:
        cmd.extend(["--idempotency-key", idempotency_key])
    cmd.append(title)

    result = _run_kanban(*cmd)
    if "id" in result:
        return result["id"]
    if "_text" in result:
        # Fallback: parse "t_abc123" from text output
        text = result["_text"]
        for token in text.split():
            if token.startswith("t_") and len(token) > 3:
                return token
    return None


def comment(task_id: str, text: str) -> bool:
    """Append a comment to a task. Returns success."""
    result = _run_kanban("comment", task_id, text)
    return bool(result)


def complete(
    task_id: str,
    result_summary: str = "",
    metadata: dict[str, Any] | None = None,
) -> bool:
    """Mark a task as done. Returns success."""
    cmd: list[str] = ["complete"]
    if result_summary:
        cmd.extend(["--result", result_summary])
    if metadata:
        cmd.extend(["--metadata", json.dumps(metadata, ensure_ascii=False)])
    cmd.append(task_id)
    result = _run_kanban(*cmd)
    return bool(result)


def block_task(
    task_id: str, reason: str = "", kind: str = "needs_input"
) -> bool:
    """Block a task. Returns success."""
    cmd = ["block", "--kind", kind, task_id]
    if reason:
        cmd.append(reason)
    result = _run_kanban(*cmd)
    return bool(result)


# ── State helpers ────────────────────────────────────────────────────────────┘


def idempotency_key(state: dict) -> str:
    """Deterministic idempotency key scoped to this pipeline run."""
    created_at = state.get("created_at", "")
    return f"pipe:{created_at}"


def ensure_task(state: dict) -> dict:
    """Create a kanban task if one doesn't exist yet.

    Mutates and returns *state* with ``kanban_task_id`` set.
    Returns state unchanged if task already exists.
    """
    if state.get("kanban_task_id"):
        return state  # Already created on a previous save

    request = state.get("request", "")
    category = state.get("category", "")
    pipeline = state.get("pipeline", [])
    agents = " → ".join(f"@{a}" for a in pipeline)

    title = f"🔷  Пайплайн: {request[:80]}"
    body = (
        f"Категория: {category}\n"
        f"Агенты: {agents}\n"
        f"Запрос: {request}"
    )
    ikey = idempotency_key(state)

    task_id = create_task(title, body=body, idempotency_key=ikey)
    if task_id:
        state["kanban_task_id"] = task_id
        logger.info("kanban task created: %s", task_id)
    else:
        logger.warning("failed to create kanban task — continuing without")
    return state


def on_convergence(state: dict, convergence_result: dict) -> None:
    """Update kanban task after convergence evaluation.

    - Comments with findings summary
    - Completes the task on converged/maxed_out/stuck
    - Blocks on stuck for human review
    """
    task_id = state.get("kanban_task_id")
    if not task_id:
        return

    decision = convergence_result.get("decision", "unknown")
    reason = convergence_result.get("reason", "")
    p0 = convergence_result.get("p0_count", 0)
    p1 = convergence_result.get("p1_count", 0)
    p2 = convergence_result.get("p2_count", 0)
    round_num = convergence_result.get("round", 0)

    # Build findings summary from state
    findings = state.get("findings", [])
    findings_lines: list[str] = []
    for f in findings:
        sev = f.get("severity", "?")
        file = f.get("file", "?")
        desc = f.get("description", "")[:60]
        findings_lines.append(f"  [{sev}] {file}: {desc}")
    findings_text = "\n".join(findings_lines) if findings_lines else "  (none)"

    summary = (
        f"Конвергенция: {decision}\n"
        f"Раунд: {round_num}  |  "
        f"P0: {p0}  P1: {p1}  P2: {p2}\n"
        f"{reason}\n\n"
        f"Findings:\n{findings_text}"
    )

    comment(task_id, summary)

    if decision == "converged":
        metadata = {
            "decision": "converged",
            "round": round_num,
            "p0": p0,
            "p1": p1,
            "p2": p2,
        }
        complete(task_id, result_summary=reason, metadata=metadata)

    elif decision == "stuck":
        block_task(
            task_id,
            reason=f"Stuck after round {round_num}: {reason}",
            kind="needs_input",
        )

    elif decision == "maxed_out":
        metadata = {
            "decision": "maxed_out",
            "round": round_num,
            "p0": p0,
            "p1": p1,
            "p2": p2,
        }
        complete(
            task_id,
            result_summary=f"Maxed out: {reason}",
            metadata=metadata,
        )


def on_clear(state: dict) -> None:
    """Close kanban task on pipeline clear (abort / cancel)."""
    task_id = state.get("kanban_task_id")
    if not task_id:
        return
    comment(task_id, "🧹 Пайплайн очищен (отмена/сброс)")
    complete(task_id, result_summary="Cancelled")
