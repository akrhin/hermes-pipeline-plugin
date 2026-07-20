name: Pull Request
description: Предложение изменений
title: ""
labels: []
body:
  - type: markdown
    attributes:
      value: |
        ## Описание
  - type: textarea
    id: summary
    attributes:
      label: Что сделано
      description: Краткое описание изменений
    validations:
      required: true
  - type: textarea
    id: motivation
    attributes:
      label: Зачем
      description: Какая задача решается (ссылка на Issue если есть)
  - type: dropdown
    id: type
    attributes:
      label: Тип изменений
      options:
        - Bug fix
        - New feature
        - Refactoring
        - Documentation
        - Dependencies
  - type: checkboxes
    id: checklist
    attributes:
      label: Чеклист
      options:
        - label: pytest tests/ -q — все проходят
          required: true
        - label: ruff check . — 0 ошибок
          required: true
        - label: plugin.yaml — версия обновлена
        - label: CHANGELOG.md — запись добавлена
        - label: AGENTS.md / ARCHITECTURE.md — обновлены если нужно
        - label: skill/pipeline-orchestrator/SKILL.md — обновлён если нужно
