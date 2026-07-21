# Architecture Fixes — Pipeline Plugin

## Сводка
Все баги, описанные в этом документе (20 шт: 4 P0 + 7 P1 + 9 P2), пофикшены к v3.3.1.
Последующие исправления — в CHANGELOG.md начиная с v3.3.2.

### Основные исправления (v3.1-v3.3)

| # | Баг | Статус |
|---|-----|--------|
| P0-1 | convergence('continue') не перезапускает coder — нет reopen() | ✅ v3.3.0 |
| P0-2 | HERMES_HOME игнорируется — нет fallback к config.yaml | ✅ v3.3.0 |
| P0-3 | LLM Judge — заглушка, не вызывает LLM | ✅ v3.3.3 |
| P0-4 | Flash-агенты без prompt (null) | ✅ v3.3.1 |
| P1-7 | 7 багов: stale cleanup, maxed_out children, scan_board LIMIT, etc | ✅ v3.3.0-3.3.1 |
| P2-9 | 9 багов: default prompt, integration.prompt Full context, doc | ✅ v3.3.0-3.3.2 |

### Аудит 2026-07-21 (v3.7.2)
- Классификатор: «аудит»/«audit» → REFACTORING (было SECURITY_RELATED)
- 17 хендлеров вынесены в handlers/ — __init__.py 892→280 строк
- Удалён мусор: 5 audit_snapshot, code_review_results, retro/*.jsonl,
  research/, ENSEMBLE-ARCHITECTURE.md, crg-pipeline-architecture.mermaid.md,
  .github/SECURITY.md (дубликат)
- 112/112 тестов, Ruff 0
