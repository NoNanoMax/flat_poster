# 🚀 DEPLOY.md — Инструкция по деплою Flat Parser

## Требования

| Ресурс | Минимум | Рекомендовано |
|--------|---------|---------------|
| GPU | NVIDIA с 24GB VRAM (RTX 3090/4090) | A100 40GB+ |
| RAM | 32 GB | 64 GB |
| CPU | 4 cores | 8 cores |
| Disk | 50 GB SSD | 100 GB NVMe |
| Docker | 20.10+ | latest |
| NVIDIA Container Toolkit | required | — |

## Шаг 1: Клонировать и подготовить

```bash
git clone git@github.com:NoNanoMax/flat_poster.git
cd flat_poster

# Скопировать .env и заполнить секреты
cp .env.example .env
nano .env   # вставить TELEGRAM_TOKEN, TELEGRAM_CHANNEL, установить FLAT_ENV=production
```

## Шаг 2: Запустить vLLM отдельно

> vLLM управляется вручную — не включён в docker-compose.
> Убедитесь что LLM-сервер работает на `http://localhost:8000/v1`.

```bash
# Пример запуска vLLM (если ещё не запущен):
# docker run --gpus all -p 8000:8000 \
#   -v ~/.cache/huggingface:/root/.cache/huggingface \
#   vllm/vllm-openai:latest \
#   --model Qwen/Qwen2.5-32B-Instruct \
#   --max-model-len 8192 \
#   --gpu-memory-utilization 0.9
```

## Шаг 3: Поднять Flat Parser

```bash
docker compose up -d
```

## Шаг 3: Проверить

```bash
# Проверить что контейнеры работают
docker compose ps

# Проверить логи
docker compose logs -f app

# Проверить health endpoint
curl http://localhost:8001/health

# Проверить readiness
curl http://localhost:8001/ready
```

### Ожидаемый вывод `/health`:

```json
{
  "status": "ok",
  "timestamp": "2025-06-29T12:00:00+00:00",
  "uptime_seconds": 120.5,
  "checks": {
    "database": {"status": "ok"},
    "llm": {"status": "ok"},
    "scheduler": {"status": "ok"}
  }
}
```

## Шаг 4: Мониторинг

```bash
# Логи приложения
docker compose logs -f app

# Логи vLLM
docker compose logs -f vllm

# Ресурсы
docker stats
```

## Конфигурация

### Поиск запросов
Редактируйте `config/search_queries.yaml` для изменения поисковых запросов:

```yaml
queries:
  - name: "Москва 1-комн вторичка до 12 млн"
    enabled: true        # true = активен, false = отключён
    source: cian
    interval_minutes: 60
    params:
      city: "Москва"
      type: "secondary"
      rooms: [1]
      price_from: 4000000
      price_to: 12000000
```

### Настройки LLM
В `config/settings.yaml`:

```yaml
llm:
  base_url: "http://localhost:8000/v1"
  model: "qwen36"
  temperature: 0.3
  max_tokens: 2000
```

### Интервалы планировщика
В `config/settings.yaml`:

```yaml
scheduler:
  fetch_listings_interval_min: 60      # каждые 60 мин
  fetch_details_interval_min: 15       # каждые 15 мин
  evaluate_new_interval_min: 20        # каждые 20 мин
  check_cold_storage_interval_min: 120 # каждые 2 часа
  cleanup_interval_hours: 24           # раз в сутки
```

## Управление

```bash
# Остановить
docker compose down

# Остановить и удалить данные (внимание: удалит БД!)
docker compose down -v

# Перезапустить
docker compose restart

# Обновить код и пересобрать
git pull
docker compose up -d --build
```

## Troubleshooting

### vLLM не стартует
- Проверьте что GPU видна: `nvidia-smi`
- Установите NVIDIA Container Toolkit: https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html
- Проверьте логи: `docker compose logs vllm`

### Telegram не отправляет уведомления
- Проверьте `TELEGRAM_TOKEN` в `.env`
- Проверьте что бот добавлен в канал как администратор
- Проверьте логи: `docker compose logs app | grep -i telegram`

### Cian возвращает капчу
- Cloudscraper обычно справляется. Если нет — проверьте IP на блокировку.
- Можно добавить прокси в `config/settings.yaml` (если потребуется)

### Высокая нагрузка на GPU
- LLM-оценка — основной bottleneck. При 20+ новых объявлениях может занять 10-25 минут.
- Параметр `max_concurrent=5` оптимален для одной GPU.

## Без Docker (прямой запуск)

```bash
# Виртуальное окружение
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Секреты
cp .env.example .env
# Заполнить .env

# Запуск
export FLAT_ENV=production
python -m src.main
```

> Для прямого запуска vLLM сервер должен быть запущен отдельно на `localhost:8000`.
