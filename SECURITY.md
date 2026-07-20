# Security Policy

## Reporting a Vulnerability

Если ты нашёл уязвимость в Hermes Pipeline Plugin — **не создавай публичный Issue**.

Напиши на **akrhin@gmail.com** с темой `[SECURITY] hermes-pipeline-plugin`.

Опиши:
- Что за уязвимость
- Как воспроизвести
- Версию плагина
- Потенциальное влияние

Ответ в течение 48 часов.

## Scope

Плагин работает внутри Hermes Agent и имеет доступ к:
- SQLite базе kanban (локальный файл)
- Системным командам через Kanban API
- Моделям LLM через провайдеры

Уязвимости, связанные с инъекцией SQL, команд ОС, или утечкой промптов — в приоритете.

## Supported Versions

| Version | Supported |
|---------|-----------|
| 3.3.x   | ✅ |
| < 3.3   | ❌ |
