#!/usr/bin/env bash
# scripts/test_evaluate.sh — Ручной запуск LLM-оценки (для отладки)
# Usage: bash scripts/test_evaluate.sh [limit]
#   limit: макс. кол-во объявлений для оценки (по умолчанию 5)

set -euo pipefail
cd "$(dirname "$0")/.."

python -c "
import asyncio
from src.config.settings import settings
from src.db.engine import init_db, close_db, session_scope
from src.db.repository import ListingRepo, EvaluationRepo
from src.agents.evaluator import EvaluationAgent

async def main():
    await init_db()
    limit = int('${1:-5}')
    async with session_scope() as session:
        repo = ListingRepo(session)
        listings = await repo.get_by_status('new', limit=limit)
        print(f'Found {len(listings)} new listings to evaluate')

    agent = EvaluationAgent()
    results = await agent.evaluate_batch(listings)

    hot = sum(1 for r in results if r.verdict == 'hot')
    warm = sum(1 for r in results if r.verdict == 'warm')
    cold = sum(1 for r in results if r.verdict == 'cold')
    reject = sum(1 for r in results if r.verdict == 'reject')
    print(f'Results: {hot} hot, {warm} warm, {cold} cold, {reject} reject')
    for r in results[:3]:
        print(f'  cian_id={r.listing_cian_id}: score={r.score} ({r.verdict}) — {r.reasons}')

    await close_db()

asyncio.run(main())
"
