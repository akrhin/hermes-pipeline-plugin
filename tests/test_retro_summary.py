"""Tests for tools/retro-summary — Pipeline Retrospective Summary."""

from __future__ import annotations

import importlib.machinery as _machinery
import importlib.util as _util
import json
import os
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Import retro-summary (extensionless executable)
_retro_path = Path(__file__).resolve().parent.parent / "tools" / "retro-summary"
_loader = _machinery.SourceFileLoader("retro_summary_mod", str(_retro_path))
_spec = _util.spec_from_loader(_loader.name, _loader, origin=str(_retro_path))
assert _spec is not None, f"Cannot load retro-summary from {_retro_path}"
rs = _util.module_from_spec(_spec)
_spec.loader.exec_module(rs)


# ── Fixtures ────────────────────────────────────────────────────────────────────


def _event(
    event: str,
    agent: str = "",
    ts: str = "2026-07-20T13:00:00+00:00",
    **kw: Any,
) -> dict[str, Any]:
    """Build a retro event dict."""
    d: dict[str, Any] = {"run": "pipe:test_run", "ts": ts, "event": event}
    if agent:
        d["agent"] = agent
    d.update(kw)
    return d


def _write_jsonl(path: Path, events: list[dict[str, Any]]) -> Path:
    with path.open("w", encoding="utf-8") as f:
        for e in events:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    return path


# ── Tests: _discover / _load ────────────────────────────────────────────────────


class TestDiscover:
    def test_discover_nonexistent_dir(self) -> None:
        assert rs._discover("/nonexistent_xyz_retro") == []

    def test_discover_empty_dir(self, tmp_path: Path) -> None:
        assert rs._discover(str(tmp_path)) == []

    def test_discover_finds_pipe_files(self, tmp_path: Path) -> None:
        (tmp_path / "pipe_a.jsonl").write_text("{}")
        (tmp_path / "pipe_b.jsonl").write_text("{}")
        (tmp_path / "other.log").write_text("{}")
        files = rs._discover(str(tmp_path))
        assert len(files) == 2
        assert all(f.suffix == ".jsonl" for f in files)
        assert all("pipe_" in f.name for f in files)


class TestLoad:
    def test_load_empty_file(self, tmp_path: Path) -> None:
        f = tmp_path / "pipe_test.jsonl"
        f.write_text("")
        assert rs._load(f) == []

    def test_load_valid_jsonl(self, tmp_path: Path) -> None:
        events = [_event("agent_start", agent="finder"), _event("agent_done", agent="finder")]
        f = _write_jsonl(tmp_path / "pipe_test.jsonl", events)
        loaded = rs._load(f)
        assert len(loaded) == 2
        assert loaded[0]["event"] == "agent_start"
        assert loaded[1]["event"] == "agent_done"

    def test_load_skips_bad_lines(self, tmp_path: Path) -> None:
        f = tmp_path / "pipe_test.jsonl"
        f.write_text(
            '{"run":"r","ts":"t","event":"agent_start","agent":"a"}\n'
            "not json\n"
            '{"run":"r","ts":"t","event":"agent_done","agent":"a"}\n'
        )
        loaded = rs._load(f)
        assert len(loaded) == 2

    def test_load_missing_file(self, tmp_path: Path) -> None:
        assert rs._load(tmp_path / "nonexistent.jsonl") == []


# ── Tests: _pts / _fts / _fdur ──────────────────────────────────────────────────


class TestTimeHelpers:
    def test_pts_valid_z(self) -> None:
        d = rs._pts("2026-07-20T13:00:00Z")
        assert d is not None
        assert d.year == 2026

    def test_pts_valid_offset(self) -> None:
        d = rs._pts("2026-07-20T13:00:00+00:00")
        assert d is not None

    def test_pts_none(self) -> None:
        assert rs._pts(None) is None

    def test_fts_none(self) -> None:
        assert rs._fts(None) == "\u2013"

    def test_fdur(self) -> None:
        assert rs._fdur("2026-07-20T13:00:00+00:00", "2026-07-20T13:05:30+00:00") is not None


# ── Tests: Summary ──────────────────────────────────────────────────────────────


class TestSummary:
    def test_empty_events(self) -> None:
        s = rs.Summary([])
        assert s.run_id == ""
        assert s.render() is not None

    def test_pipeline_start(self) -> None:
        events = [_event("pipeline_start", category="FEATURE", agents=4, request="test")]
        s = rs.Summary(events)
        assert s.run_id == "pipe:test_run"
        assert s.category == "FEATURE"
        assert s.request == "test"
        assert s.agent_count == 4

    def test_agent_sequence(self) -> None:
        events = [
            _event("agent_start", agent="finder"),
            _event("agent_start", agent="analyst"),
            _event("agent_start", agent="finder"),
        ]
        s = rs.Summary(events)
        assert list(s.agents.keys()) == ["finder", "analyst"]

    def test_agent_durations(self) -> None:
        events = [
            _event("agent_start", agent="finder", ts="2026-07-20T13:00:00+00:00"),
            _event("agent_done", agent="finder", ts="2026-07-20T13:00:15+00:00"),
        ]
        s = rs.Summary(events)
        assert abs(s.agents["finder"]["dur_s"] - 15.0) < 1.0

    def test_convergence(self) -> None:
        events = [_event("convergence", round=1, decision="converged", p0=0, p1=0, p2=2, reason="OK")]
        s = rs.Summary(events)
        assert len(s.convergences) == 1
        assert s.convergences[0]["decision"] == "converged"

    def test_findings(self) -> None:
        events = [_event("findings", p0=1, p1=2, p2=3, fixed=0, accepted=0)]
        s = rs.Summary(events)
        assert len(s.findings) == 1
        assert s.findings[0]["p0"] == 1

    def test_ensemble(self) -> None:
        events = [
            _event("ensemble_gen", agent="coder", n=5, temperatures=[0.3, 0.5]),
            _event("ensemble_judge", winner="candidate_3", mode="llm", rationale="Best"),
        ]
        s = rs.Summary(events)
        assert len(s.ensembles) == 1
        assert s.ensembles[0]["agent"] == "coder"

    def test_errors(self) -> None:
        events = [_event("error", agent="tester", error="Test failed", resolution="Fixed")]
        s = rs.Summary(events)
        assert len(s.errors) == 1
        assert s.errors[0]["error"] == "Test failed"

    def test_duration_s(self) -> None:
        events = [
            _event("pipeline_start", ts="2026-07-20T13:00:00+00:00"),
            _event("pipeline_clear", ts="2026-07-20T13:10:00+00:00"),
        ]
        s = rs.Summary(events)
        assert abs(s.duration_s - 600.0) < 1.0

    def test_render_returns_string(self) -> None:
        events = [_event("pipeline_start", category="FEATURE", request="hello")]
        s = rs.Summary(events)
        rendered = s.render()
        assert isinstance(rendered, str)
        assert len(rendered) > 10

    def test_to_dict_keys(self) -> None:
        events = [_event("pipeline_start", category="BUG")]
        s = rs.Summary(events)
        d = s.to_dict()
        assert "run_id" in d
        assert "category" in d
        assert "agents" in d
        assert "total_duration_s" in d
        assert "event_count" in d

    def test_to_dict_agents_list(self) -> None:
        events = [
            _event("agent_start", agent="finder"),
            _event("agent_done", agent="finder", ts="2026-07-20T13:01:00+00:00"),
        ]
        s = rs.Summary(events)
        d = s.to_dict()
        assert len(d["agents"]) == 1
        assert d["agents"][0]["name"] == "finder"


# ── Tests: CLI / main ───────────────────────────────────────────────────────────


class TestCLI:
    def test_parse_args_default(self) -> None:
        args = rs.parse_args([])
        assert args.dir == rs.DEFAULT_DIR
        assert args.last == 1
        assert args.all is False
        assert args.json is False
        assert args.verbose is False

    def test_parse_args_custom(self) -> None:
        args = rs.parse_args(["--dir", "/tmp", "--all", "--json", "-v"])
        assert args.dir == "/tmp"
        assert args.all is True
        assert args.json is True
        assert args.verbose is True

    def test_parse_args_last(self) -> None:
        args = rs.parse_args(["--last", "3"])
        assert args.last == 3

    def test_main_no_logs(self, capsys) -> None:
        rc = rs.main(["--dir", "/nonexistent_xyz_retro"])
        assert rc != 0
        captured = capsys.readouterr()
        assert "No retro logs" in captured.err or "not found" in captured.err

    def test_main_runs_with_real_data(self, tmp_path: Path, monkeypatch, capsys) -> None:
        events = [
            _event("pipeline_start", category="TEST", agents=2, request="integration test"),
            _event("agent_start", agent="finder", directive="direct"),
            _event("agent_done", agent="finder"),
        ]
        f = _write_jsonl(tmp_path / "pipe_integration.jsonl", events)
        rc = rs.main(["--dir", str(tmp_path)])
        assert rc == 0
        captured = capsys.readouterr()
        assert "integration test" in captured.out or "pipe:test_run" in captured.out

    def test_main_json_output(self, tmp_path: Path, monkeypatch, capsys) -> None:
        events = [
            _event("pipeline_start", category="TEST", agents=1, request="json test"),
            _event("agent_start", agent="finder"),
            _event("agent_done", agent="finder"),
        ]
        f = _write_jsonl(tmp_path / "pipe_json.jsonl", events)
        rc = rs.main(["--dir", str(tmp_path), "--json"])
        assert rc == 0
        captured = capsys.readouterr()
        parsed = json.loads(captured.out)
        assert parsed["run_id"] == "pipe:test_run"
        assert parsed["category"] == "TEST"
        assert len(parsed["agents"]) == 1
        assert parsed["event_count"] == 3

    def test_main_no_color_flag(self, tmp_path: Path, capsys) -> None:
        events = [_event("pipeline_start", category="TEST")]
        _write_jsonl(tmp_path / "pipe_nocolor.jsonl", events)
        rc = rs.main(["--dir", str(tmp_path), "--no-color"])
        assert rc == 0
        captured = capsys.readouterr()
        # No ANSI escape codes in output
        assert "\033" not in captured.out


# ── Integration: full round-trip ────────────────────────────────────────────────


class TestIntegration:
    def test_full_pipeline_run(self, tmp_path: Path) -> None:
        events = [
            _event("pipeline_start", category="FEATURE", agents=5, request="full integration test", ts="2026-07-20T13:00:00+00:00"),
            _event("agent_start", agent="finder", directive="direct", model="flash", ts="2026-07-20T13:00:05+00:00"),
            _event("agent_done", agent="finder", ts="2026-07-20T13:00:20+00:00"),
            _event("agent_start", agent="analyst", directive="direct", model="flash", ts="2026-07-20T13:00:22+00:00"),
            _event("agent_done", agent="analyst", ts="2026-07-20T13:00:35+00:00"),
            _event("agent_start", agent="coder", directive="direct", model="flash", ts="2026-07-20T13:00:37+00:00"),
            _event("ensemble_gen", agent="coder", n=3, temperatures=[0.3, 0.5, 0.7], ts="2026-07-20T13:00:40+00:00"),
            _event("ensemble_judge", winner="candidate_1", mode="llm", rationale="best pick", ts="2026-07-20T13:01:00+00:00"),
            _event("convergence", round=1, decision="converged", p0=0, p1=0, p2=1, reason="all good", ts="2026-07-20T13:01:30+00:00"),
            _event("findings", p0=0, p1=0, p2=1, fixed=0, accepted=0, ts="2026-07-20T13:01:30+00:00"),
            _event("error", agent="tester", error="timeout", resolution="retried", ts="2026-07-20T13:02:00+00:00"),
            _event("pipeline_clear", ts="2026-07-20T13:02:05+00:00"),
        ]

        f = _write_jsonl(tmp_path / "pipe_full.jsonl", events)
        loaded = rs._load(f)
        assert len(loaded) == 12

        s = rs.Summary(loaded, path=f)
        assert s.run_id == "pipe:test_run"
        assert s.category == "FEATURE"
        assert s.request == "full integration test"
        assert list(s.agents.keys()) == ["finder", "analyst", "coder"]
        assert len(s.convergences) == 1
        assert s.convergences[0]["decision"] == "converged"
        assert len(s.findings) == 1
        assert len(s.errors) == 1
        assert len(s.ensembles) == 1
        assert s.duration_s > 0

        # Render produces output
        rendered = s.render(verbose=True)
        assert "full integration test" in rendered
        assert "finder" in rendered
        assert "analyst" in rendered
        assert "converged" in rendered

        # JSON round-trip
        d = s.to_dict()
        assert d["category"] == "FEATURE"
        assert d["convergence_decision"] == "converged"
        assert len(d["agents"]) == 3
        assert len(d["errors"]) == 1
        assert len(d["ensembles"]) == 1
        assert d["event_count"] == 12

    def test_unicode_roundtrip(self, tmp_path: Path) -> None:
        events = [_event("pipeline_start", category="FEATURE", agents=1, request="\u0434\u043e\u0431\u0430\u0432\u044c \u043a\u043e\u043c\u0430\u043d\u0434\u0443")]
        f = _write_jsonl(tmp_path / "pipe_unicode.jsonl", events)
        s = rs.Summary(rs._load(f))
        assert "\u0434\u043e\u0431\u0430\u0432\u044c" in s.render()
