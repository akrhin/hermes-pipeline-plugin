# Changelog

## [1.1.0] — 2026-07-18

### Added

- **Hermes Kanban Dashboard** — прогресс пайплайна публикуется на встроенную Kanban-доску Hermes (`~/.hermes/kanban.db`, доска `home`). Каждая стадия — task, статусы: ready → running → done. Связи через `link`, комментарии через `comment`.
- **Convergence guard** — `pipeline_convergence()` без findings и пустом state возвращает `unknown`, а не ложный `converged`. Исправлен AUDIT-001.
- **CHANGELOG.md** — потому что пора.

### Changed

- **SKILL.md** — версия 1.0.0 → 1.1.0. Удалена секция TickTick Kanban (~60 строк). Добавлена секция Hermes Kanban (~90 строк) c bash-шаблонами: `create --body` (статус `ready`), `complete`, `block`, `comment`, `link`, `list`.
- **ARCHITECTURE.md** — файловый tree приведён к реальности: удалён stale `.cursor/backlog/`, добавлены `tests/`, `LICENSE`, `pyproject.toml`, `.github/workflows/`.
- **README.md** — удалён stale `.cursor/backlog/` и дубликат `.github/workflows/` из файлового tree. Оба языка (ru + en) синхронизированы.

### Removed

- **TickTick MCP** — интеграция удалена. Больше никаких внешних kanban-сервисов.
- **`research/`** — stale JSON (19KB) от предыдущих сессий.
- **`.cursor/backlog/`** — stale логи (перенесены в Git history).

### Fixed

- **AUDIT-001** — ложный `converged` на пустом пайплайне. Теперь `unknown`.
- **AUDIT-003** — dead code в `evaluate_convergence()` (недостижимый второй converged-блок). Удалён.
- **AUDIT-005** — `fsync()` уже был, подтверждён.
- **AUDIT-006** — `allow_nan=False` уже был, подтверждён.
- **Path traversal** — `handle_prompt()` проверяет resolved path через `os.path.realpath()`. Исправлено ранее.
- **Braces escaping** — `{` → `{{` в user-controlled строках `handle_prompt()`. Исправлено ранее.
- **None-безопасный fingerprint** — `f.get('description') or ''` вместо `f.get('description', '')`. Исправлено ранее.

## [1.0.0] — 2026-07-18

### Added

- Плагин-оркестратор multi-agent пайплайнов для Hermes Agent.
- 7 инструментов: `pipeline_classify`, `pipeline_convergence`, `pipeline_save`, `pipeline_load`, `pipeline_clear`, `agent_prompt`, `agent_model`.
- 8 категорий классификации: FEATURE, SECURITY_RELATED, BUG_UNKNOWN, BUG_KNOWN, REFACTORING, PERFORMANCE, INFRASTRUCTURE, DOCUMENTATION.
- Keyword-based классификация (без LLM).
- Детерминированный convergence cycle (без LLM): max 3 раунда, fingerprint-сравнение P0/P1.
- Модельный роутинг: Flash (direct), Pro (delegate), OpenRouter free (delegate_free).
- 4 prompt-шаблона: architect, reviewer, security, researcher.
- TickTick Kanban dashboard (v1 — удалён в 1.1.0).
- 58 unit-тестов, ruff-линтер, bandit SAST, CI через GitHub Actions.
- Документация: README (ru + en), ARCHITECTURE.md, AGENTS.md, LICENSE (MIT).
