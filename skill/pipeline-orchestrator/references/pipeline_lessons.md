# Lessons from Pipeline Plugin Refactoring

(This file documents recurring gotchas learned during real refactoring sessions.)

## Common Issues & Fixes

1. **Timezone bugs** — ensure `_now_iso()` returns UTC; `_iso_to_ts()` must interpret input as UTC (use `calendar.timegm`).
2. **Lint configuration** — add `pyproject.toml` with ruff settings; ignore N999 for hyphenated dirs, E501 line length, F401 unused imports.
3. **CI workflow** — use ruff + bandit + compileall + pytest; update actions to use latest compatible versions (e.g., golangci-lint v2 for Go 1.25).
4. **Version bumps** — minor bumps only; match `go.mod` Go version to CI runner.
5. **Test isolation** — write pure-function tests; avoid importing modules with hyphens; use wrapper methods if needed.
6. **Dependency handling** — when testing plugins that depend on host Hermes, mock or test pure functions; add module-level shims for class methods.
7. **Release process** — tag with `v*`; ensure release workflow exists; delete mistaken tags before re-tagging.
8. **Static analysis** — fix real issues found by linters (e.g., `os.Remove` without context, `conn.Close` missing defer, `fmt.Fprintf` vs `Sprint`).

## Workflow Tips

- Run `@finder → @analyst → @researcher → @architect → @planner → @coder → @reviewer → @security → @tester → @documenter` via pipeline plugin.
- Use `delegate_task` for large docs; keep sub-tasks independent.
- After each patch, run `ruff check .` and `pytest -q` locally before pushing.
- If CI fails on lint, check tool version compatibility (e.g., golangci-lint v2 needs Go ≥1.24).
- For Bandit false positives on hard-coded URLs, add `# nosec` comment.
