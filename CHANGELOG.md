# Changelog

## v1.2.0 (2026-07-18)

### Features
- **@integration** agent: cross-file integration checks (install.sh URLs, README→files, CI→Makefile)
- **Kanban Dashboard**: migrated from TickTick prototype to Hermes-native Kanban

### Changes
- **classify.py**: `integration` added to SECURITY, FEATURE, REFACTORING pipelines
- **__init__.py**: `integration` in MODEL_MAP (delegate, DeepSeek V4 Pro)
- **agents/integration.prompt**: new prompt template
- **AGENTS.md**: updated model routing + pipeline sequence + Kanban guide
- **pipeline-orchestrator** skill: TickTick → Hermes Kanban
- **pipeline-convergence-engine** skill: Integration Agent documentation
- **references/integration-gap-findings.md**: install.sh 404 postmortem

### Pipeline (full audit sequence)

```
@finder → @analyst → @researcher → @architect → @planner → @coder
→ @reviewer → @security → @integration → @tester → @documenter
```

## v1.1.0 (2026-07-18)

- Remove stale `.cursor/backlog` files
- Refactor: cleanup stale references, add convergence guard
- Replace TickTick Kanban with built-in Hermes Kanban
- Fix path traversal vulnerability in `handle_prompt`
- Documentation: add CHANGELOG.md, bump plugin.yaml to 1.1.0

## v1.0.0 (2026-07-18)

- Initial release
- 7 tools: classify, convergence, save, load, clear, prompt, model
- 8 categories: SECURITY, BUG_UNKNOWN, BUG_KNOWN, REFACTORING, PERFORMANCE, INFRASTRUCTURE, DOCUMENTATION, FEATURE
- 12 agents: finder, analyst, researcher, architect, planner, coder, editor, fixer, refactorer, tester, debugger, documenter, devops, optimizer, commenter
- Model routing: Flash (direct) / Pro (delegate) / Free (OpenRouter)
- State persistence with convergence (max 3 rounds, fingerprint-based stuck detection)
