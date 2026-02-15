# Mastermind Coach Bot

Telegram-бот для ежедневного коучинга: утренний mind dump (голосом или текстом), структурированный анализ через LLM, фокус дня, мини-чекины и вечерний отчёт.

## Стек

- Python 3.12+
- aiogram 3.x (Telegram Bot API)
- PostgreSQL + SQLAlchemy 2.x (async) + Alembic
- APScheduler (утренние пинги, чекины, вечерние напоминания)
- OpenAI-compatible API (GPT для анализа, Whisper для транскрипции)

## Быстрый старт

### 1. Клонировать и установить зависимости

```bash
cd mastermind_bot
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS/Linux
source .venv/bin/activate

pip install -r requirements.txt
```

### 2. Поднять PostgreSQL

```bash
docker compose up -d
```

### 3. Настроить переменные окружения

```bash
copy .env.example .env
```

Заполнить `.env`:
- `BOT_TOKEN` — токен от @BotFather
- `LLM_API_KEY` — ключ OpenAI (или совместимого API)
- `WHISPER_API_KEY` — ключ для Whisper API (может быть тот же, что и LLM)

### 4. Применить миграции

```bash
alembic upgrade head
```

Или при первом запуске бот сам создаст таблицы (dev-режим).

### 5. Запустить бота

```bash
python -m bot
```

## Создание миграций

После изменения моделей в `bot/db/models.py`:

```bash
alembic revision --autogenerate -m "описание изменений"
alembic upgrade head
```

## Структура проекта

```
mastermind_bot/
├── bot/
│   ├── __main__.py          # Точка входа
│   ├── config.py             # Настройки из .env
│   ├── db/
│   │   ├── base.py           # DeclarativeBase
│   │   ├── models.py         # SQLAlchemy модели
│   │   └── session.py        # Async engine + session
│   ├── handlers/
│   │   ├── start.py          # /start
│   │   ├── onboarding.py     # Онбординг (сферы, фокусы, тон, время)
│   │   ├── dump.py           # Mind dump (голос + текст)
│   │   ├── focus.py          # Выбор фокуса A/B + энергия
│   │   ├── checkin.py        # Мини-чекины (+3ч, +6ч)
│   │   ├── evening.py        # Вечерний отчёт
│   │   ├── deeper.py         # "Копнуть глубже"
│   │   └── settings.py       # Настройки пользователя
│   ├── keyboards/
│   │   └── inline.py         # Все клавиатуры
│   ├── middlewares/
│   │   └── db.py             # Инжекция DB session + User
│   ├── prompts/
│   │   ├── analyze_dump.py   # Промпт анализа dump (v1)
│   │   └── go_deeper.py      # Промпт глубинной сессии (v1)
│   ├── services/
│   │   ├── llm_client.py     # Абстракция LLM (OpenAI-compatible)
│   │   ├── transcriber.py    # Whisper транскрипция
│   │   ├── coach_engine.py   # CoachEngine (анализ + coaching)
│   │   └── scheduler_service.py  # APScheduler jobs
│   ├── states/
│   │   └── fsm.py            # FSM-состояния
│   └── utils/
│       └── analytics.py      # Логирование событий
├── knowledge/                 # Коучинговые протоколы (RU)
│   ├── grow.md
│   ├── woop.md
│   ├── if_then.md
│   ├── microstep_timebox.md
│   ├── eisenhower.md
│   ├── impact_effort.md
│   ├── reframe.md
│   ├── gentle_discipline.md
│   ├── anti_slip.md
│   └── help_request.md
├── alembic/                   # Миграции БД
├── alembic.ini
├── docker-compose.yml
├── requirements.txt
└── .env.example
```

## Основной flow (Phase 0)

1. `/start` → онбординг (сферы, фокус недели/месяца, тон, время пинга)
2. Утренний пинг в настроенное время
3. Пользователь отправляет **голосовое** или **текст** → транскрипция → LLM-анализ
4. Бот выдаёт: зеркало эмоций, задачи, 2 варианта фокуса дня (A/B)
5. Пользователь выбирает вариант, подтверждает энергию
6. Через 3 и 6 часов — мини-чекины
7. Вечером — отчёт (статус + 3 строки текста)
8. Если LLM обнаружил тревогу — предложение "копнуть глубже"

## Переменные окружения

| Переменная | Описание | Обязательно |
|---|---|---|
| `BOT_TOKEN` | Telegram bot token | Да |
| `DATABASE_URL` | PostgreSQL connection string | Да |
| `LLM_API_KEY` | OpenAI API key | Да |
| `LLM_BASE_URL` | API base URL | Нет (default: OpenAI) |
| `LLM_MODEL` | Модель для анализа | Нет (default: gpt-4o-mini) |
| `WHISPER_API_KEY` | Whisper API key | Да |
| `WHISPER_MODEL` | Модель транскрипции | Нет (default: whisper-1) |
