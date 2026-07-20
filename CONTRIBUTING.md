# Contributing to Hermes Pipeline Plugin

Спасибо, что хочешь помочь проекту! 🎉

## Как контрибьютить

### 1. Найди задачу
- Посмотри открытые [Issues](https://github.com/akrhin/hermes-pipeline-plugin/issues)
- Если хочешь предложить новую фичу — создай Issue с описанием

### 2. Форкни и работай

```bash
git clone https://github.com/ВАШ_НИК/hermes-pipeline-plugin.git
cd hermes-pipeline-plugin
git checkout -b feature/ваше-изменение
```

### 3. Код-стайл

- Python: следуй PEP 8. Проверяй `ruff check .` (должен быть 0 ошибок)
- Импорты: одна строка на импорт (даже внутри try/except) — ruff I001
- Длина строки: 100 символов
- Все публичные функции должны быть типизированы (type hints)

### 4. Тесты

```bash
pytest tests/ -q
```

**Все тесты должны проходить:** 79/79 (v3.3.3).

Если добавляешь новую фичу — напиши тест. Если фиксишь баг — добавь регрессионный тест.

### 5. Архитектура плагина

Прочитай [AGENTS.md](AGENTS.md) — там всё про 16 агентов, 8 категорий, selective context.

Основные файлы:

| Файл | Назначение |
|------|-----------|
| `__init__.py` | 12 инструментов, AGENT_CONTEXT_FIELDS, handle_* функции |
| `kanban.py` | SQLite-native Kanban API |
| `ensemble.py` | Best-of-N ensemble (generate_candidates, judge_candidates) |
| `classify.py` | Классификация запроса по 8 категориям |
| `models.py` | Model routing + hot-reload config |
| `agents/*.prompt` | Промпты для каждого из 16 агентов |
| `skill/pipeline-orchestrator/SKILL.md` | Главный оркестратор-скилл |

### 6. Pull Request

- Создай PR в ветку `main`
- В описании укажи: что сделано, зачем, как тестировал
- Убедись что CI проходит: `pytest tests/ -q` + `ruff check .`
- Не забывай обновить `CHANGELOG.md` и `plugin.yaml` версию

### 7. Документация

Если твой PR меняет поведение плагина — обнови:

- `CHANGELOG.md` — новая запись
- `AGENTS.md` — если менялись агенты или категории
- `ARCHITECTURE.md` — если менялась архитектура
- `skill/pipeline-orchestrator/SKILL.md` — главный скилл оркестрации
- `plugin.yaml` — версия и описание

### 8. Вопросы

Пиши в Issues или на akrhin@gmail.com.
