# docs/architecture.md — Архитектура Flat Parser

## Обзор

Flat Parser — асинхронное приложение на Python 3.10, которое парсит объявления о продаже квартир на Cian.ru,
оценивает их через локальную LLM (qwen36 / vLLM) и отправляет уведомления в Telegram.

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Flat Parser App                              │
│                                                                     │
│  ┌──────────┐   ┌──────────────┐   ┌─────────────┐                │
│  │  Cian    │──▶│  Listing     │──▶│  Evaluator  │                │
│  │  Scraper │   │  Repo (DB)   │   │  Agent      │                │
│  └──────────┘   └──────────────┘   └──────┬──────┘                │
│                                            │                        │
│                                      ┌─────▼──────┐                │
│                                      │  Notifier   │──▶ Telegram   │
│                                      │  (Console   │    Channel    │
│                                      │   / TG)     │                │
│                                      └─────────────┘                │
│                                                                     │
│  ┌──────────────┐    ┌──────────────┐    ┌─────────────┐          │
│  │ Cold Storage │    │ Scheduler    │    │ Health      │          │
│  │  Manager     │    │  Runner      │    │  Server     │          │
│  └──────────────┘    └──────────────┘    └─────────────┘          │
└─────────────────────────────────────────────────────────────────────┘
         │                        │                   │
         ▼                        ▼                   ▼
    cian.ru              SQLite / PG         FastAPI :8001
         │
         ▼
    vLLM :8000  (qwen36, управляется отдельно)
```

## Пайплайн данных

1. **fetch_listings** (каждые 60 мин) — парсит страницу поиска по каждому enabled-запросу → сохраняет RawListing в БД со статусом `new`
2. **fetch_details** (каждые 15 мин) — для `new` объявлений без площади загружает полную карточку → обогащает поля
3. **evaluate_new** (каждые 20 мин) — LLM-оценка `new` объявлений → verdict: hot/warm/cold/reject
   - HOT → мгновенное уведомление в Telegram
   - WARM/COLD → попадают в cold storage для последующей перепроверки
4. **check_cold_storage** (каждые 2 часа) — перепроверяет warm/cold:
   - Цена упала >5% → RE_EVALUATE (переоценка через LLM)
   - ESCALATE (стало hot после переоценки) → уведомление
   - REMOVE (5 провалов / TTL истёк / объявление удалено на Cian)
5. **cleanup** (каждые 24 часа) — удаляет просроченные записи

## Модули

| Модуль | Файл | Назначение |
|--------|------|------------|
| Config | `config/settings.py`, `config/queries.py` | Pydantic-settings, YAML-загрузка, .env |
| DB | `db/models.py`, `db/engine.py`, `db/repository.py` | SQLAlchemy 2.0 async, 4 модели, 4 репозитория |
| Scraper | `scrapers/cian.py`, `scrapers/base.py`, `scrapers/parsers/*.py` | cloudscraper, brace-counting JSON-парсинг |
| Agent | `agents/agent_runner.py`, `agents/evaluator.py` | AsyncOpenAI wrapper, evaluate_batch (parallel, mc=5) |
| Notifier | `notifier/formatter.py`, `notifier/console.py`, `notifier/telegram.py` | MarkdownV2, ANSI, aiogram Bot |
| Cold Storage | `cold_storage/manager.py`, `cold_storage/strategies.py` | Warm/Cold/Removal стратегии, re-evaluate |
| Scheduler | `scheduler/jobs.py`, `scheduler/runner.py` | APScheduler AsyncIOScheduler, 5 jobs + retry |
| Health | `health_server.py` | FastAPI /health + /ready на порту 8001 |

## Конфигурация

- `config/settings.yaml` — все настройки (LLM, Telegram, DB, scheduler intervals)
- `config/search_queries.yaml` — поисковые запросы (name, enabled, params)
- `.env` — секреты (TELEGRAM_TOKEN, TELEGRAM_CHANNEL)
- `FLAT_ENV=production` → автоматически `test_mode=false`

## Конкурентность

- LLM-оценка: `asyncio.Semaphore(max_concurrent=5)` + `asyncio.gather()` — ускорение ×3.4
- HTTP-запросы: `asyncio.to_thread()` — cloudscraper блокирующий, выполняется в потоке
- APScheduler: задачи выполняются последовательно внутри одного job (не параллельно между собой)

## Базы данных

- **Dev:** SQLite (`sqlite+aiosqlite:///./data/realty.db`)
- **Prod:** PostgreSQL (`postgresql+asyncpg://user:pass@host:5432/realty`) — переключается через `database.url` в settings.yaml

## Мониторинг

- `/health` (порт 8001) — статус DB, LLM, scheduler
- `/ready` (порт 8001) — readiness probe
- Логи: `logs/app.log` (loguru, rotation 10 MB, retention 30 дней)
