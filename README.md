# 🏠 Flat Parser

Автономная система мониторинга недвижимости с LLM-оценкой. Парсит объявления с Циана, оценивает их через локальную LLM (qwen36) и публикует лучшие варианты в Telegram-канал.

## Возможности

- **Периодический парсинг** Циана по настраиваемым запросам (новостройки и вторичка)
- **LLM-оценка** каждого объявления: цена, локация, качество, инвестиционный потенциал
- **Telegram-уведомления** о лучших вариантах (hot deals)
- **Холодная база** — отслеживание потенциально интересных вариантов, перепроверка при снижении цены
- **Автоматическая очистка** — удаление просроченных и неактуальных объявлений
- **Market Analyst агент** — LLM анализирует рынок и корректирует поисковые запросы

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

## Холодная база

- **WARM:** перепроверка каждые 24 часа
- **COLD:** перепроверка каждые 72 часа
- При снижении цены > 5% → переоценка через LLM
- После 5 проверок без улучшений → удаление
- Максимальный TTL: 30 дней

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

## CI/CD

- **Lint:** ruff + mypy на каждом PR
- **Test:** pytest на каждом PR

## Roadmap

- [x] Этап 1: Фундамент (БД, конфиги, main)
- [ ] Этап 2: Парсинг Циана
- [ ] Этап 3: Агент-оценщик (LLM)
- [ ] Этап 4: Уведомления (Telegram + console)
- [ ] Этап 5: Холодная база
- [ ] Этап 6: Планировщик + интеграция
- [ ] Этап 7: Market Analyst Agent
- [ ] Этап 8: Полировка

## Лицензия

MIT
