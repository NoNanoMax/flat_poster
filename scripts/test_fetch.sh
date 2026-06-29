#!/usr/bin/env bash
# scripts/test_fetch.sh — Ручной запуск парсера (для отладки)
# Usage: bash scripts/test_fetch.sh [query_name]
#   query_name: имя из config/search_queries.yaml (по умолчанию первый enabled)

set -euo pipefail
cd "$(dirname "$0")/.."

python -c "
import asyncio
from src.config.settings import settings
from src.config.queries import load_search_queries
from src.db.engine import init_db, close_db
from src.db.repository import ListingRepo, SearchQueryRepo
from src.scrapers.cian import CianScraper

async def main():
    await init_db()
    queries = load_search_queries()
    q = '${1:-}'
    if q:
        queries = [x for x in queries if x.name == q]
    if not queries:
        queries = [next((x for x in load_search_queries() if x.enabled), None) or load_search_queries()[0]]
    scraper = CianScraper()
    for query in queries:
        print(f'Fetching: {query.name}')
        listings = await scraper.fetch_search_page(query.params, page=1)
        print(f'  Found {len(listings)} listings')
        for l in listings[:3]:
            print(f'  - {l.rooms}к {l.total_area}м² {l.price}₽ {l.address}')
    await close_db()

asyncio.run(main())
"
