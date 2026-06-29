# 🏠 Flat Parser

Автономная система мониторинга недвижимости с LLM-оценкой. Парсит объявления с Циана, оценивает их через локальную LLM (qwen36) и публикует лучшие варианты в Telegram-канал.

## Возможности

- **Парсинг Циана** (✅ реализовано) — извлекает поиск + детали карточки через cloudscraper с обходом анти-бота
- **LLM-оценка** (✅ реализовано) — qwen36 через vLLM: цена, локация, качество, инвестиционный потенциал
- **Telegram-уведомления** о лучших вариантах (hot deals)
- **Холодная база** — отслеживание потенциально интересных вариантов, перепроверка при снижении цены
- **Автоматическая очистка** — удаление просроченных и неактуальных объявлений
- **Market Analyst агент** (🚧 в планах) — LLM будет анализировать рынок и корректировать поисковые запросы

## Архитектура

```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│  Scraper    │────▶│   Database   │◀────│ Cold Storage │
│  (Cian)     │     │  (SQLite)    │     │   Manager    │
└─────────────┘     └──────┬───────┘     └─────────────┘
                           │
                           ▼
                    ┌──────────────┐     ┌──────────────┐
                    │   Evaluator  │────▶│  Notifier    │
                    │   (LLM)      │     │ (Telegram)   │
                    └──────────────┘     └──────────────┘
                           ▲
                           │
                    ┌──────────────┐
                    │   Scheduler  │
                    │ (APScheduler)│
                    └──────────────┘
```

## Структура проекта

```
flat_parser/
├── src/
│   ├── main.py                  # Точка входа
│   ├── config/                  # Загрузка конфигов (YAML + .env)
│   ├── db/                      # SQLAlchemy модели + репозитории
│   ├── scrapers/                # Парсеры (Cian, base ABC)
│   ├── agents/                  # LLM-агенты (evaluator, market_analyst)
│   ├── notifier/                # Уведомления (Telegram, console)
│   ├── scheduler/               # Планировщик задач
│   └── cold_storage/            # Менеджер холодной базы
├── tests/                       # Тесты (pytest)
├── config/                      # Конфигурация
│   ├── settings.yaml            # Основные настройки
│   └── search_queries.yaml      # Поисковые запросы
├── .github/workflows/           # CI/CD (lint + test)
├── scripts/                     # Ручные утилиты
├── docs/                        # Документация
├── requirements.txt
├── pyproject.toml
└── Makefile
```

## Требования

- Python 3.10+
- Локальный vllm-сервер с моделью qwen36 на `http://localhost:8000/v1`
- Telegram Bot Token (для продакшен-режима)

## Установка

```bash
# Клонировать репозиторий
cd flat_parser

# Создать виртуальное окружение
python -m venv .venv
source .venv/bin/activate

# Установить зависимости
pip install -r requirements.txt

# Скопировать .env (для Telegram)
cp .env.example .env
# Редактировать .env: вставить TELEGRAM_TOKEN и TELEGRAM_CHANNEL
```

## Запуск

```bash
# Запуск системы
make run
# или
python -m src.main
```

## Конфигурация

### `config/settings.yaml`

Основные настройки: LLM, Telegram, БД, логирование, скрапер, планировщик, холодная база.

```yaml
llm:
  base_url: "http://localhost:8000/v1"
  model: "qwen36"
  temperature: 0.3

telegram:
  test_mode: true    # true = консоль, false = Telegram

database:
  url: "sqlite+aiosqlite:///./data/realty.db"
```

### `config/search_queries.yaml`

Поисковые запросы для Циана:

```yaml
queries:
  - name: "Москва 1-комн вторичка до 12 млн"
    enabled: true
    source: cian
    interval_minutes: 60
    params:
      city: "Москва"
      type: "secondary"
      rooms: [1]
      price_from: 4000000
      price_to: 12000000
      area_from: 25
      area_to: 45
```

### `.env`

Секреты (не коммитить):

```
TELEGRAM_TOKEN=your_bot_token
TELEGRAM_CHANNEL=@your_channel
```

## Скрапер Циана (реализовано)

Скрапер использует `cloudscraper` для обхода анти-бота и парсит inline-JSON из `<script>` тегов:

### Страница поиска
- URL: `https://cian.ru/cat.php?p=1&deal_type=sale&offer_type=flat&region=1&...`
- Извлекает массив `products` из inline JSON
- Поля: `cianId`, `price`, `objectType`, `photosCount`, `owner`, `goodPrice`

### Страница объявления
- URL: `https://www.cian.ru/sale/flat/<cianId>/`
- Извлекает объект `offerData.offer` из inline JSON
- Поля: `title`, `description`, `roomsCount`, `totalArea`, `livingArea`, `kitchenArea`, `floorNumber`, `building`, `geo.address`, `geo.undergrounds`, `geo.jk`, `photos`, `repairType`, `isByHomeowner`

### Использование в коде

```python
from src.config.settings import settings
from src.scrapers.cian import CianScraper

scraper = CianScraper(settings.scraper)

# Поиск
brief_listings = await scraper.fetch_search_page(query, page=1)

# Детали
detailed = await scraper.fetch_listing_details(cian_id, brief=brief)
```

### Region IDs
| Город | ID |
|-------|-----|
| Москва | 1 |
| Московская область | 650 |

## Агент-оценщик (реализовано)

Оценка объявлений через локальную LLM (qwen36 через vLLM):

### Архитектура
```
Listing (БД) → EvaluationAgent → LLMClient → vLLM (qwen36) → JSON → EvaluationResult → БД
```

### Критерии оценки
- **Цена (40%)** — цена/м² vs рынок района
- **Локация (25%)** — район, метро, инфраструктура
- **Качество (20%)** — ремонт, этаж, тип дома, год постройки
- **Инвестиции (15%)** — ликвидность, потенциал роста

### Использование

```python
from src.config.settings import settings
from src.agents.agent_runner import LLMClient
from src.agents.evaluator import EvaluationAgent

llm = LLMClient(settings.llm)
agent = EvaluationAgent(llm)

# Оценка одного объявления
result = await agent.evaluate(listing)
# → score=85, verdict="hot", pros=[...], cons=[...]

# Пакетная оценка + сохранение в БД
results = await agent.evaluate_batch(session, limit=10)
```

### Технические детали
- Модель qwen36 **всегда** пишет reasoning (built-in), финальный ответ в `content`
- JSON mode: `response_format={"type": "json_object"}` + `enable_thinking=False`
- Auto retry при truncation (увеличение max_tokens ×1.5)
- max_tokens ≥ 4000 для полных оценок

## Режимы работы

| Режим | `test_mode` | Куда вывод |
|-------|-------------|------------|
| Тестовый | `true` | Консоль + `logs/telegram_test.log` |
| Продакшен | `false` | Telegram-канал |

## Расписание задач

| Задача | Интервал | Описание |
|--------|----------|----------|
| `fetch_listings` | 60 мин | Парсинг Циана по всем запросам |
| `fetch_details` | 15 мин | Загрузка деталей новых объявлений |
| `evaluate_new` | 20 мин | Оценка новых объявлений через LLM |
| `check_cold_storage` | 2 часа | Перепроверка холодной базы |
| `cleanup_expired` | 24 часа | Удаление просроченных вариантов |

## Вердикты LLM

| Вердикт | Оценка | Действие |
|---------|--------|----------|
| 🔥 HOT | 80–100 | Публикуем в Telegram |
| ☀️ WARM | 60–79 | Холодная база, проверка каждые 24ч |
| ❄️ COLD | 40–59 | Холодная база, проверка каждые 72ч |
| ✗ REJECT | 0–39 | Не храним |

## Холодная база (реализовано)

Система отслеживания потенциально интересных вариантов с периодической перепроверкой:

- **WARM:** перепроверка каждые 24 часа
- **COLD:** перепроверка каждые 72 часа
- При снижении цены > 5% → переоценка через LLM
- Если переоценка дала HOT → автоматическое уведомление в Telegram (эскалация)
- После 5 проверок без улучшений → удаление
- Максимальный TTL: 30 дней

### Использование

```python
from src.cold_storage.manager import ColdStorageManager

manager = ColdStorageManager(
    settings=settings.cold_storage,
    scraper=scraper,
    evaluator=evaluator,
    notifier=notifier,
)

# Перепроверить холодную базу
stats = await manager.run_check(session)
# → {"checked": 12, "re_evaluated": 3, "escalated": 1, "skipped": 7, "removed": 1, "errors": 0}

# Очистить просроченные
removed = await manager.run_cleanup(session)
# → 5
```

## Разработка

```bash
# Запуск тестов
make test

# Линтинг
make lint

# Форматирование
make format

# Проверка конфига
make init

# Очистка артефактов
make clean
```

## Деплой

Полная инструкция — [DEPLOY.md](DEPLOY.md). Кратко:

```bash
# 1. Секреты
cp .env.example .env
nano .env   # TELEGRAM_TOKEN, TELEGRAM_CHANNEL, FLAT_ENV=production

# 2. Запустить vLLM (отдельно, вручную)
# docker run --gpus all -p 8000:8000 vllm/vllm-openai:latest --model Qwen/Qwen2.5-32B-Instruct ...

# 3. Поднять приложение
docker compose up -d

# 4. Проверить
curl http://localhost:8001/health
```

## Мониторинг

| Endpoint | URL | Описание |
|----------|-----|----------|
| Health | `GET /health` (порт 8001) | Статус DB, LLM, scheduler → 200 (ok) / 503 (degraded) |
| Ready | `GET /ready` (порт 8001) | Readiness probe — scheduler запущен? |
| Логи | `logs/app.log` | loguru: rotation 10 MB, retention 30 дней |
| Docker | `docker compose logs -f app` | Live-логи контейнера |

## CI/CD

- **Lint:** ruff + mypy на каждом PR
- **Test:** pytest на каждом PR

## Roadmap

- [x] Этап 1: Фундамент (БД, конфиги, main)
- [x] Этап 2: Парсинг Циана (search page + listing details, cloudscraper, 48 тестов)
- [x] Этап 3: Агент-оценщик (LLMClient, EvaluationAgent, vLLM qwen36, 16 тестов)
- [x] Этап 4: Уведомления (Telegram + console, 32 теста)
- [x] Этап 5: Холодная база (стратегии warm/cold, переоценка, TTL, 39 тестов)
- [x] Этап 6: Планировщик + интеграция (APScheduler, 5 jobs, 19 тестов)
- [ ] Этап 7: Market Analyst Agent (LLM генерирует поисковые запросы)
- [ ] Этап 8: Полировка (документация, скрипты, финальные тесты)

## Лицензия

MIT
