# Pipeline Plugin

Multi-agent pipeline orchestrator for Hermes Agent.

Автоматизирует сложные задачи через последовательность специализированных агентов
с quality gates (reviewer + tester после каждого изменения, security для sensitive задач).

## Installation

```bash
git clone https://github.com/YOUR_USER/hermes-pipeline-plugin ~/git/hermes-pipeline-plugin
ln -sf ~/git/hermes-pipeline-plugin ~/.hermes/plugins/pipeline
hermes plugins enable pipeline
```

## Usage

```
/pipeline Добавить JWT-аутентификацию    — запуск пайплайна
/review auth.go                            — только ревью
/test auth_test.go                         — только тесты
/security auth.go                          — только security-аудит
/status                                    — статус текущего пайплайна
/abort                                     — отмена
```

## Architecture

См. [ARCHITECTURE.md](ARCHITECTURE.md)

## Agent Instructions

См. [AGENTS.md](AGENTS.md)
