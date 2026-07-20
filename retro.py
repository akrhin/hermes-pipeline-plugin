"""
Pipeline Retrospective — structured pipeline run log + self-analysis.

Each pipeline run writes a JSONL file (~/.hermes/plugins/pipeline/retro/).
Events are structural metadata: agent_start/done, convergence, model_routing,
errors. No raw prompts or responses — only what's needed for analysis.

Auto-analysis: on maxed_out/stuck convergence, the pipeline analyzes its own
log and generates improvement suggestions (findings + fixes).
"""

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────

DEFAULT_RETRO_CONFIG = {
    "enabled": True,
    "dir": "~/.hermes/plugins/pipeline/retro",
    "max_files": 100,
    "auto_analyze": False,
}


def _read_retro_config(config_path: str | None = None) -> dict:
    """Read retro config from pipeline config.yaml. Returns defaults if missing."""
    if not config_path:
        hermes_home = os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes"))
        config_path = str(Path(hermes_home) / "plugins" / "pipeline" / "config.yaml")

    try:
        import yaml

        with open(config_path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)
    except Exception:
        return dict(DEFAULT_RETRO_CONFIG)

    try:
        pipeline = raw.get("pipeline", {}) if isinstance(raw, dict) else {}
        rc = pipeline.get("retro", {})
        if not isinstance(rc, dict):
            return dict(DEFAULT_RETRO_CONFIG)
        # Merge with defaults
        merged = dict(DEFAULT_RETRO_CONFIG)
        merged.update(rc)
        return merged
    except Exception:
        return dict(DEFAULT_RETRO_CONFIG)


# ── File management ────────────────────────────────────────────────────────────


def _ensure_retro_dir(config: dict) -> str | None:
    """Create retro directory if it doesn't exist. Returns path or None."""
    if not config.get("enabled", True):
        return None
    retro_dir = os.path.expanduser(config.get("dir", DEFAULT_RETRO_CONFIG["dir"]))
    try:
        Path(retro_dir).mkdir(parents=True, exist_ok=True)
        return retro_dir
    except OSError as e:
        logger.warning("Cannot create retro dir %s: %s", retro_dir, e)
        return None


def _rotate_if_needed(retro_dir: str, config: dict) -> None:
    """Remove oldest files if count exceeds max_files."""
    max_files = config.get("max_files", DEFAULT_RETRO_CONFIG["max_files"])
    try:
        files = sorted(
            Path(retro_dir).glob("pipe_*.jsonl"),
            key=lambda p: p.stat().st_mtime,
        )
        while len(files) > max_files:
            oldest = files.pop(0)
            oldest.unlink(missing_ok=True)
            logger.info("Rotated old retro log: %s", oldest.name)
    except OSError:
        pass


# ── Event writer ────────────────────────────────────────────────────────────────


class RetroLogger:
    """Structured logger for pipeline retrospectives.

    Usage:
        retro = RetroLogger(run_id="pipe:abc123")
        retro.log("agent_start", agent="finder", directive="direct")
        retro.log("agent_done", agent="finder", duration_s=3.2)
    """

    def __init__(self, run_id: str = ""):
        self._run_id = run_id
        self._file = None
        self._path = None
        self._config = _read_retro_config()
        self._enabled = self._config.get("enabled", True)
        self._dir = _ensure_retro_dir(self._config)
        if self._dir and self._enabled:
            _rotate_if_needed(self._dir, self._config)

    def set_run_id(self, run_id: str) -> None:
        """Set or update the run_id (called when pipeline_save creates a parent)."""
        self._run_id = run_id

    def _open(self) -> None:
        """Open the JSONL file for this run."""
        if self._file is not None:
            return
        if not self._dir or not self._enabled:
            return
        if not self._run_id:
            return

        # Sanitize run_id for filename
        safe_id = self._run_id.replace(":", "_").replace("/", "_")
        self._path = Path(self._dir) / f"pipe_{safe_id}.jsonl"
        try:
            self._file = self._path.open("a", encoding="utf-8")
        except OSError as e:
            logger.warning("Cannot open retro log %s: %s", self._path, e)

    def log(self, event: str, **kwargs) -> None:
        """Write a structured event to the retro log.

        Args:
            event: Event type (agent_start, agent_done, convergence, etc.)
            **kwargs: Event-specific fields (agent, duration_s, model, etc.)
        """
        if not self._enabled:
            return

        self._open()
        if self._file is None:
            return

        record = {
            "run": self._run_id,
            "ts": datetime.now(timezone.utc).isoformat(),
            "event": event,
        }
        record.update(kwargs)

        try:
            self._file.write(json.dumps(record, ensure_ascii=False) + "\n")
            self._file.flush()
        except OSError as e:
            logger.warning("Cannot write retro log: %s", e)

    def close(self) -> None:
        """Close the log file."""
        if self._file:
            try:
                self._file.close()
            except OSError:
                pass
            self._file = None

    # ── Convenience log methods ────────────────────────────────────────────────

    def agent_start(
        self,
        agent: str,
        directive: str,
        model: str,
        round: int = 0,
        tokens_prompt: int | None = None,
    ) -> None:
        self.log(
            "agent_start",
            agent=agent,
            directive=directive,
            model=model,
            round=round,
            tokens_prompt=tokens_prompt,
        )

    def agent_done(
        self, agent: str, duration_s: float, result: str = "", tokens_response: int | None = None
    ) -> None:
        self.log(
            "agent_done",
            agent=agent,
            duration_s=round(duration_s, 2),
            result=result,
            tokens_response=tokens_response,
        )

    def convergence(
        self,
        round: int,
        decision: str,
        p0: int,
        p1: int,
        p2: int,
        fingerprint: str = "",
        reason: str = "",
    ) -> None:
        self.log(
            "convergence",
            round=round,
            decision=decision,
            p0=p0,
            p1=p1,
            p2=p2,
            fingerprint=fingerprint,
            reason=reason,
        )

    def model_routing(self, agent: str, effective: str, configured: str, warning: str = "") -> None:
        self.log(
            "model_routing",
            agent=agent,
            effective=effective,
            configured=configured,
            warning=warning,
        )

    def ensemble_gen(self, agent: str, n: int, temperatures: list[float]) -> None:
        self.log("ensemble_gen", agent=agent, n=n, temperatures=temperatures)

    def ensemble_judge(self, winner: str, mode: str, rationale: str = "") -> None:
        self.log("ensemble_judge", winner=winner, mode=mode, rationale=rationale)

    def context_selective(
        self, agent: str, sections: list[str], tokens_saved: int | None = None
    ) -> None:
        self.log("context_selective", agent=agent, sections=sections, tokens_saved=tokens_saved)

    def findings_event(self, p0: int, p1: int, p2: int, fixed: int = 0, accepted: int = 0) -> None:
        self.log("findings", p0=p0, p1=p1, p2=p2, fixed=fixed, accepted=accepted)

    def error(self, agent: str, error: str, resolution: str = "") -> None:
        self.log("error", agent=agent, error=error, resolution=resolution)

    def findings_detail(self, findings: list[dict]) -> None:
        """Log the detailed findings list as a single event."""
        self.log("findings_detail", count=len(findings), items=findings)


# ── Global singleton ───────────────────────────────────────────────────────────

# Simple approach: one retro logger per pipeline run.
# The orchestrator creates a new retro when pipeline_save is called.
_ACTIVE_RETRO: RetroLogger | None = None


def get_retro(run_id: str = "") -> RetroLogger:
    """Get or create the active retro logger for this pipeline run."""
    global _ACTIVE_RETRO
    if _ACTIVE_RETRO is None:
        _ACTIVE_RETRO = RetroLogger(run_id=run_id)
    elif run_id:
        _ACTIVE_RETRO.set_run_id(run_id)
    return _ACTIVE_RETRO


def reset_retro() -> None:
    """Close and reset the active retro logger."""
    global _ACTIVE_RETRO
    if _ACTIVE_RETRO:
        _ACTIVE_RETRO.close()
    _ACTIVE_RETRO = None


# ── Analysis ────────────────────────────────────────────────────────────────────


def get_latest_log(limit: int = 1) -> list[dict]:
    """Read the most recent retro log(s). Returns list of events."""
    config = _read_retro_config()
    if not config.get("enabled", True):
        return []

    retro_dir = os.path.expanduser(config.get("dir", DEFAULT_RETRO_CONFIG["dir"]))
    try:
        files = sorted(
            Path(retro_dir).glob("pipe_*.jsonl"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
    except OSError:
        return []

    events = []
    for f in files[:limit]:
        try:
            with open(f, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if line:
                        try:
                            events.append(json.loads(line))
                        except json.JSONDecodeError:
                            continue
        except OSError:
            continue
        # Only read full first file, snippet from rest
        if len(events) > 500:
            break
    return events


def build_analysis_prompt(events: list[dict], run_context: dict | None = None) -> str:
    """Build a structured analysis prompt from retro events for LLM consumption.

    The output is a text summary that an LLM can analyze to find
    pipeline issues, anti-patterns, and improvement suggestions.
    """
    if not events:
        return "No retro events to analyze."

    # Extract key metrics
    agents_run = []
    durations = {}
    errors = []
    convergences = []
    routings = []
    ensembles = []
    findings_events = []
    events_by_type = {}

    for e in events:
        evt = e.get("event", "")
        events_by_type.setdefault(evt, 0)
        events_by_type[evt] += 1

        if evt == "agent_start":
            agents_run.append(e.get("agent", "?"))
        elif evt == "agent_done":
            agent = e.get("agent", "?")
            durations[agent] = e.get("duration_s", 0)
        elif evt == "error":
            errors.append(e)
        elif evt == "convergence":
            convergences.append(e)
        elif evt == "model_routing":
            routings.append(e)
        elif evt == "ensemble_gen":
            ensembles.append(e)
        elif evt == "findings":
            findings_events.append(e)

    # Build the analysis text
    lines = [
        "## Pipeline Retrospective Analysis",
        "",
        f"Event types: {json.dumps(events_by_type, ensure_ascii=False, indent=2)}",
        "",
    ]

    if agents_run:
        agents_str = " → ".join(agents_run)
        lines.append(f"### Agent sequence ({len(agents_run)} agents)")
        lines.append(f"  {agents_str}")
        lines.append("")

    if durations:
        lines.append("### Per-agent duration (seconds)")
        for agent, dur in sorted(durations.items(), key=lambda x: -x[1]):
            lines.append(f"  {agent}: {dur:.1f}s")
        lines.append("")

    if convergences:
        lines.append("### Convergence rounds")
        for c in convergences:
            lines.append(
                f"  Round {c.get('round', '?')}: {c.get('decision', '?')} — "
                f"P0={c.get('p0', 0)} P1={c.get('p1', 0)} P2={c.get('p2', 0)}"
            )
            reason = c.get("reason", "")
            if reason:
                lines.append(f"    reason: {reason}")
        lines.append("")

    if routings:
        lines.append("### Model routing events")
        warnings = [r for r in routings if r.get("warning")]
        if warnings:
            lines.append("  ⚠️  Warnings:")
            for r in warnings:
                lines.append(f"    - {r['agent']}: {r['warning']}")
        else:
            lines.append("  All clean — no routing warnings")
        lines.append("")

    if ensembles:
        lines.append("### Ensemble runs")
        for e in ensembles:
            lines.append(
                f"  {e.get('agent', '?')}: N={e.get('n', 0)} temps={e.get('temperatures', [])}"
            )
        lines.append("")

    if errors:
        lines.append("### Errors")
        for err in errors:
            resolution = err.get("resolution", "")
            resolution_suffix = f" → {resolution}" if resolution else ""
            lines.append(
                f"  ❌ {err.get('agent', '?')}: {err.get('error', '?')}{resolution_suffix}"
            )
        lines.append("")

    if findings_events:
        lines.append("### Findings summary")
        for f in findings_events:
            lines.append(
                f"  P0={f.get('p0', 0)} P1={f.get('p1', 0)} P2={f.get('p2', 0)} "
                f"fixed={f.get('fixed', 0)} accepted={f.get('accepted', 0)}"
            )
        lines.append("")

    # Detect patterns and anti-patterns
    patterns = []

    # 1. Convergence always maxed_out
    if convergences:
        last_decision = convergences[-1].get("decision", "")
        if last_decision == "maxed_out":
            patterns.append(
                "⚠️  Convergence: maxed_out — findings remained after max rounds. "
                "Check if convergence correctly filters 'fixed' findings."
            )
        elif last_decision == "stuck":
            patterns.append(
                "⚠️  Convergence: stuck — same findings across rounds. "
                "Fix convergence or remove stale findings."
            )
        elif last_decision == "converged":
            patterns.append("✅ Convergence: converged — all P0/P1 resolved.")

    # 2. Ensemble always deterministic
    ensemble_judge_events = [e for e in events if e.get("event") == "ensemble_judge"]
    if ensemble_judge_events:
        all_deterministic = all(e.get("mode") == "deterministic" for e in ensemble_judge_events)
        if all_deterministic:
            patterns.append(
                "ℹ️  Ensemble judge always used deterministic mode — "
                "LLM Judge was never invoked. Check model availability."
            )

    # 3. Routing warnings
    if routings:
        stale_routes = [r for r in routings if "stale" in r.get("warning", "").lower()]
        if stale_routes:
            models_str = ", ".join(
                f"{r['agent']} (wanted: {r.get('configured', '?')})" for r in stale_routes
            )
            patterns.append(
                f"⚠️  Stale MODEL_MAP detected for: {models_str}. "
                "Config change was not picked up — add hot-reload."
            )

    # 4. Errors
    if errors:
        patterns.append(f"❌ {len(errors)} error(s) during pipeline run — review above.")

    # 5. Long-running agents
    slow_agents = [(a, d) for a, d in durations.items() if d > 30]
    if slow_agents:
        agents_str = ", ".join(f"{a} ({d:.0f}s)" for a, d in slow_agents)
        patterns.append(f"🐢 Slow agents: {agents_str}. Check if selective context is optimal.")

    if patterns:
        lines.append("### Detected patterns & suggestions")
        for p in patterns:
            lines.append(f"  {p}")
        lines.append("")

    lines.append("### Raw events")
    lines.append(f"  {len(events)} total events")
    for i, e in enumerate(events):
        if i >= 50:
            lines.append(f"  ... and {len(events) - 50} more events")
            break
        # Compact one-line summary
        evt = e.get("event", "?")
        agent = e.get("agent", e.get("decision", ""))
        extra = ""
        if evt == "agent_start":
            extra = f" round={e.get('round', 0)}"
        elif evt == "agent_done":
            extra = f" {e.get('duration_s', 0)}s"
        elif evt == "convergence":
            extra = f" {e.get('decision', '?')} P0={e.get('p0', 0)}"
        elif evt == "model_routing":
            extra = f" {agent} → {e.get('effective', '?')}"
            if e.get("warning"):
                extra += " ⚠️"
        elif evt == "error":
            extra = f" {agent}: {e.get('error', '?')[:60]}"
        line = f"  [{e.get('ts', '?')[-12:-7]}] {evt:20s}{extra}"
        lines.append(line)

    return "\n".join(lines)
