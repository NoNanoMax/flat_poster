"""Scheduler jobs — async functions that APScheduler calls on a schedule."""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import Awaitable
from functools import wraps
from typing import TypeVar

from loguru import logger

from src.agents.agent_runner import LLMClient
from src.agents.evaluator import EvaluationAgent
from src.cold_storage.manager import ColdStorageManager
from src.config.queries import SearchParams
from src.config.queries import SearchQuery as ConfigSearchQuery
from src.config.settings import settings
from src.db.engine import session_scope
from src.db.models import SearchQuery as DBSearchQuery
from src.db.repository import EvaluationRepo, ListingRepo, SearchQueryRepo
from src.notifier.console import ConsoleNotifier, NotifierABC
from src.notifier.formatter import ListingFormatter
from src.notifier.telegram import TelegramNotifier
from src.scrapers.cian import CianScraper

# ── Retry wrapper for jobs ───────────────────────────────────────────────────

T = TypeVar("T", bound=Awaitable[object])


def retry_job(max_retries: int = 2, base_delay: float = 30.0):
    """Decorator: retry an async job with exponential backoff on failure.

    Args:
        max_retries: Number of retries after the first attempt.
        base_delay: Initial delay in seconds between retries.
    """

    def decorator(func: T) -> T:
        @wraps(func)
        async def wrapper(*args, **kwargs):  # type: ignore[no-untyped-def]
            last_exc: Exception | None = None
            for attempt in range(1 + max_retries):
                try:
                    return await func(*args, **kwargs)
                except Exception as exc:
                    last_exc = exc
                    if attempt < max_retries:
                        delay = base_delay * (2 ** attempt)
                        logger.warning(
                            "Job '{}' failed (attempt {}/{}): {} — retrying in {:.0f}s",
                            func.__name__,
                            attempt + 1,
                            1 + max_retries,
                            exc,
                            delay,
                        )
                        await asyncio.sleep(delay)
                    else:
                        logger.critical(
                            "Job '{}' FAILED after {} attempts: {}",
                            func.__name__,
                            1 + max_retries,
                            last_exc,
                        )
                        # Alert via console (always) — in production this could
                        # also send to Telegram or a monitoring system
                        logger.critical(
                            "🚨 CRITICAL: Job '{}' is DOWN — manual intervention required!",
                            func.__name__,
                        )

        return wrapper  # type: ignore[return-value]

    return decorator

# ── DB → config converter ────────────────────────────────────────────────────


def _to_config_query(db_q: DBSearchQuery) -> ConfigSearchQuery:
    """Convert DB SearchQuery model to config SearchQuery dataclass for the scraper."""
    params_dict: dict = {}
    if db_q.query_params:
        with contextlib.suppress(json.JSONDecodeError, TypeError):
            params_dict = json.loads(db_q.query_params)
    return ConfigSearchQuery(
        name=db_q.name,
        enabled=db_q.enabled,
        source=db_q.source,
        interval_minutes=db_q.interval_minutes,
        max_pages=db_q.max_pages,
        params=SearchParams(
            city=params_dict.get("city", "Москва"),
            listing_type=params_dict.get("type", "secondary"),
            rooms=params_dict.get("rooms", []),
            price_from=params_dict.get("price_from"),
            price_to=params_dict.get("price_to"),
            area_from=params_dict.get("area_from"),
            area_to=params_dict.get("area_to"),
            build_year_from=params_dict.get("build_year_from"),
            developer=params_dict.get("developer"),
        ),
    )


# ── Notifier factory ─────────────────────────────────────────────────────────


def _get_notifier() -> NotifierABC:
    """Create appropriate notifier based on settings."""
    if settings.telegram.test_mode or not settings.telegram.token:
        return ConsoleNotifier()
    return TelegramNotifier(settings.telegram)


# ── Job: fetch_listings ──────────────────────────────────────────────────────


@retry_job(max_retries=2, base_delay=30.0)
async def fetch_listings_job() -> None:
    """Fetch new listings from Cian for all enabled search queries."""
    async with session_scope() as session:
        query_repo = SearchQueryRepo(session)
        listing_repo = ListingRepo(session)
        db_queries = await query_repo.get_enabled()

        if not db_queries:
            logger.info("Fetch listings: no enabled queries")
            return

        scraper = CianScraper(settings.scraper)
        total_new = 0
        total_skipped = 0

        for db_q in db_queries:
            query = _to_config_query(db_q)
            try:
                listings = await scraper.fetch_search_page(query, page=1)
                for brief in listings:
                    existing = await listing_repo.get_by_cian_id(brief.cian_id)
                    if not existing:
                        data = brief.to_dict()
                        data["status"] = "new"
                        await listing_repo.upsert(data)
                        total_new += 1
                    else:
                        total_skipped += 1
                # Commit after each query to avoid SQLite lock on large batches
                await session.commit()
            except Exception as exc:
                await session.rollback()
                logger.error(
                    "Fetch listings error for query '{}': {}",
                    query.name,
                    exc,
                )

        logger.info(
            "Fetch listings: {} new, {} skipped, from {} queries",
            total_new,
            total_skipped,
            len(db_queries),
        )


# ── Job: fetch_details ───────────────────────────────────────────────────────


@retry_job(max_retries=2, base_delay=30.0)
async def fetch_details_job() -> None:
    """Fetch full details for new listings that are missing them."""
    async with session_scope() as session:
        listing_repo = ListingRepo(session)
        new_listings = await listing_repo.get_by_status("new")

        # Filter to those missing details (area is None)
        pending = [listing for listing in new_listings if listing.area is None]

        if not pending:
            logger.info("Fetch details: nothing to do")
            return

        scraper = CianScraper(settings.scraper)
        updated = 0
        errors = 0

        for listing in pending:
            try:
                details = await scraper.fetch_listing_details(listing.cian_id, brief=None)
                if details:
                    data = details.to_dict()
                    await listing_repo.upsert(data)
                    updated += 1
            except Exception as exc:
                logger.error(
                    "Fetch details error for cian_id={}: {}",
                    listing.cian_id,
                    exc,
                )
                errors += 1

        logger.info(
            "Fetch details: updated {}, errors {}, skipped {}", updated, errors, len(pending) - updated - errors
        )


# ── Job: evaluate_new ────────────────────────────────────────────────────────


@retry_job(max_retries=1, base_delay=60.0)
async def evaluate_new_job() -> None:
    """Evaluate all new listings via LLM and notify for hot ones."""
    async with session_scope() as session:
        llm = LLMClient(settings.llm)
        evaluator = EvaluationAgent(llm)

        results = await evaluator.evaluate_batch(session, limit=20)

        if not results:
            logger.info("Evaluate new: nothing to evaluate")
            return

        # Send notifications for hot listings — fetch them from DB after evaluation
        notifier = _get_notifier()
        formatter = ListingFormatter()
        eval_repo = EvaluationRepo(session)
        listing_repo = ListingRepo(session)

        hot_listings = await listing_repo.get_by_status("hot")
        hot_count = 0

        for listing in hot_listings:
            latest_eval = await eval_repo.get_latest(listing.id)
            if latest_eval:
                hot_count += 1
                text = formatter.format_for_telegram(listing, latest_eval)
                photo_url = None
                if listing.photos and isinstance(listing.photos, list) and listing.photos:
                    photo_url = listing.photos[0]
                try:
                    await notifier.send(text, photo_url=photo_url)
                except Exception as exc:
                    logger.error(
                        "Notification error for cian_id={}: {}",
                        listing.cian_id,
                        exc,
                    )

        # Close TelegramNotifier if needed (ConsoleNotifier.close is no-op)
        if isinstance(notifier, TelegramNotifier):
            await notifier.close()

        logger.info(
            "Evaluate new: {} evaluated, {} hot, {} warm, {} cold, {} reject",
            len(results),
            hot_count,
            sum(1 for r in results if r.verdict == "warm"),
            sum(1 for r in results if r.verdict == "cold"),
            sum(1 for r in results if r.verdict == "reject"),
        )


# ── Job: check_cold_storage ──────────────────────────────────────────────────


@retry_job(max_retries=1, base_delay=60.0)
async def check_cold_storage_job() -> None:
    """Re-check warm/cold listings in cold storage."""
    async with session_scope() as session:
        scraper = CianScraper(settings.scraper)
        llm = LLMClient(settings.llm)
        evaluator = EvaluationAgent(llm)
        notifier = _get_notifier()

        manager = ColdStorageManager(
            settings=settings.cold_storage,
            scraper=scraper,
            evaluator=evaluator,
            notifier=notifier,
        )

        stats = await manager.run_check(session)

        if isinstance(notifier, TelegramNotifier):
            await notifier.close()

        logger.info("Cold storage check: {}", stats)


# ── Job: cleanup ─────────────────────────────────────────────────────────────


@retry_job(max_retries=1, base_delay=60.0)
async def cleanup_job() -> None:
    """Remove expired listings from cold storage."""
    async with session_scope() as session:
        scraper = CianScraper(settings.scraper)
        llm = LLMClient(settings.llm)
        evaluator = EvaluationAgent(llm)
        notifier = _get_notifier()

        manager = ColdStorageManager(
            settings=settings.cold_storage,
            scraper=scraper,
            evaluator=evaluator,
            notifier=notifier,
        )

        removed = await manager.run_cleanup(session)

        if isinstance(notifier, TelegramNotifier):
            await notifier.close()

        logger.info("Cleanup: removed {} listings", removed)
