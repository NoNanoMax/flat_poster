"""Cold storage manager — orchestrates re-checking and cleanup of cold listings."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from src.agents.evaluator import EvaluationAgent
from src.cold_storage.strategies import (
    CheckAction,
    CheckResult,
    RemovalStrategy,
    determine_action,
    get_strategy_for_verdict,
)
from src.config.settings import ColdStorageSettings
from src.db.models import Listing
from src.db.repository import EvaluationRepo, ListingRepo
from src.notifier.console import NotifierABC
from src.notifier.formatter import ListingFormatter
from src.scrapers.cian import CianScraper


class ColdStorageManager:
    """Manages warm/cold listings: re-checking, re-evaluation, escalation, cleanup.

    Workflow per check cycle:
    1. Fetch listings due for re-check (warm/cold with next_check_at <= now)
    2. For each listing:
       a. Determine strategy (warm → 24h, cold → 72h)
       b. Re-scrape listing details to get current price
       c. Determine action (RE_EVALUATE / SKIP / REMOVE)
       d. Execute action
    3. Return statistics
    """

    def __init__(
        self,
        settings: ColdStorageSettings,
        scraper: CianScraper,
        evaluator: EvaluationAgent,
        notifier: NotifierABC,
    ):
        self._settings = settings
        self._scraper = scraper
        self._evaluator = evaluator
        self._notifier = notifier
        self._formatter = ListingFormatter()

    # ── Public API ─────────────────────────────────────────────────────────

    async def run_check(self, session: AsyncSession) -> dict[str, int]:
        """Run one cold storage re-check cycle.

        Returns:
            Stats dict: {"checked": N, "re_evaluated": N, "escalated": N,
                         "skipped": N, "removed": N, "errors": N}
        """
        repo = ListingRepo(session)
        listings = await repo.get_for_cold_check()

        if not listings:
            logger.info("Cold storage: no listings due for re-check")
            return {"checked": 0, "re_evaluated": 0, "escalated": 0, "skipped": 0, "removed": 0, "errors": 0}

        logger.info("Cold storage: checking {} listings", len(listings))

        stats: dict[str, int] = {
            "checked": len(listings),
            "re_evaluated": 0,
            "escalated": 0,
            "skipped": 0,
            "removed": 0,
            "errors": 0,
        }

        for listing in listings:
            try:
                result = await self._check_single(session, listing)
                self._update_stats(stats, result)
            except Exception as exc:
                logger.error("Cold storage error on cian_id={}: {}", listing.cian_id, exc)
                stats["errors"] += 1

            # Rate limit between requests
            await asyncio.sleep(self._scraper._settings.delay_between_requests)  # type: ignore[attr-defined]

        logger.info("Cold storage check complete: {}", stats)
        return stats

    async def run_cleanup(self, session: AsyncSession) -> int:
        """Remove expired / delisted listings.

        Returns:
            Number of listings removed.
        """
        repo = ListingRepo(session)

        # 1. Explicitly expired (max checks exceeded)
        expired = await repo.get_expired()
        removed = 0

        for listing in expired:
            await repo.delete(listing)
            removed += 1

        # 2. TTL expired (created_at + ttl_days < now)
        ttl_cutoff = datetime.now(timezone.utc) - timedelta(days=self._settings.ttl_days)
        warm_listings = list(await repo.get_by_status("warm"))
        cold_listings = list(await repo.get_by_status("cold"))

        for listing in warm_listings + cold_listings:
            if listing.created_at and listing.created_at < ttl_cutoff:
                await repo.delete(listing)
                removed += 1
                logger.info("Cleanup: removed cian_id={} (TTL expired)", listing.cian_id)

        logger.info("Cold storage cleanup: removed {} listings", removed)
        return removed

    # ── Internal helpers ───────────────────────────────────────────────────

    async def _check_single(
        self,
        session: AsyncSession,
        listing: Listing,
    ) -> CheckResult:
        """Check a single listing and execute the determined action."""
        repo = ListingRepo(session)

        # Determine strategy based on current verdict
        strategy = get_strategy_for_verdict(listing.last_verdict or listing.status)

        # Increment check count
        listing.cold_check_count += 1

        # Check removal rules BEFORE scraping (saves HTTP requests).
        # We use RemovalStrategy directly — determine_action with new_price=None
        # would always return REMOVE for non-max-checks cases.
        removal = RemovalStrategy()
        if removal.should_remove(listing, self._settings):
            result = CheckResult(
                cian_id=listing.cian_id,
                action=CheckAction.REMOVE,
                old_price=listing.price,
            )
            await repo.delete(listing)
            logger.info(
                "Removed cian_id={} ({} checks, TTL check)",
                listing.cian_id,
                listing.cold_check_count,
            )
            return result

        # Re-scrape to get current price
        new_price = await self._fetch_current_price(listing)

        # Determine action with price info
        action = determine_action(listing, new_price, self._settings)

        # Execute action
        if action == CheckAction.REMOVE:
            await repo.delete(listing)
            return CheckResult(
                cian_id=listing.cian_id,
                action=CheckAction.REMOVE,
                old_price=listing.price,
                new_price=new_price,
            )

        if action == CheckAction.RE_EVALUATE:
            return await self._re_evaluate(session, listing, new_price, strategy)

        # SKIP — just bump next_check_at
        listing.next_check_at = strategy.next_check_at(listing)
        listing.last_checked = datetime.now(timezone.utc)
        logger.info(
            "Skipped cian_id={} (price stable, next check: {})",
            listing.cian_id,
            listing.next_check_at,
        )
        return CheckResult(
            cian_id=listing.cian_id,
            action=CheckAction.SKIP,
            old_price=listing.price,
            new_price=new_price,
        )

    async def _fetch_current_price(self, listing: Listing) -> int | None:
        """Fetch the current price of a listing from Cian.

        Returns None if the listing is delisted or fetch failed.
        """
        try:
            details = await self._scraper.fetch_listing_details(
                listing.cian_id,  # type: ignore[arg-type]
                brief=None,
            )
            if details is None:
                return None
            return details.price
        except Exception as exc:
            logger.warning(
                "Failed to fetch price for cian_id={}: {}",
                listing.cian_id,
                exc,
            )
            return None

    async def _re_evaluate(
        self,
        session: AsyncSession,
        listing: Listing,
        new_price: int | None,
        strategy,
    ) -> CheckResult:
        """Re-evaluate a listing via LLM and handle the result."""
        # Update price in listing before evaluation
        if new_price is not None and new_price != listing.price:
            old_price = listing.price
            listing.update_price(new_price)
            logger.info(
                "Price changed cian_id={}: {} → {}",
                listing.cian_id,
                old_price,
                new_price,
            )

        # Re-evaluate via LLM
        try:
            result = await self._evaluator.evaluate_and_save(session, listing)
        except Exception as exc:
            logger.error(
                "Re-evaluation failed for cian_id={}: {}",
                listing.cian_id,
                exc,
            )
            # On failure, just bump next_check_at and retry later
            listing.next_check_at = strategy.next_check_at(listing)
            return CheckResult(
                cian_id=listing.cian_id,
                action=CheckAction.RE_EVALUATE,
                old_price=listing.price,
                new_price=new_price,
            )

        # Check if verdict improved to HOT
        if result.verdict == "hot":
            # Send notification
            latest_eval = await EvaluationRepo(session).get_latest(listing.id)
            if latest_eval:
                await self._notifier.send(
                    self._formatter.format_for_telegram(listing, latest_eval),
                    photo_url=(listing.photos and listing.photos[0] if isinstance(listing.photos, list) else None),
                )
                logger.info("Escalated cian_id={} to HOT — notification sent", listing.cian_id)
            return CheckResult(
                cian_id=listing.cian_id,
                action=CheckAction.ESCALATE,
                old_price=listing.price,
                new_price=new_price,
                re_eval_score=result.score,
                re_eval_verdict=result.verdict,
            )

        # Verdict stayed warm/cold — bump next_check_at
        listing.next_check_at = strategy.next_check_at(listing)
        logger.info(
            "Re-evaluated cian_id={}: score={:.0f}, verdict={} (no escalation)",
            listing.cian_id,
            result.score,
            result.verdict,
        )
        return CheckResult(
            cian_id=listing.cian_id,
            action=CheckAction.RE_EVALUATE,
            old_price=listing.price,
            new_price=new_price,
            re_eval_score=result.score,
            re_eval_verdict=result.verdict,
        )

    @staticmethod
    def _update_stats(stats: dict[str, int], result: CheckResult) -> None:
        """Update stats dict based on check result."""
        if result.action == CheckAction.RE_EVALUATE:
            stats["re_evaluated"] += 1
        elif result.action == CheckAction.ESCALATE:
            stats["escalated"] += 1
        elif result.action == CheckAction.SKIP:
            stats["skipped"] += 1
        elif result.action == CheckAction.REMOVE:
            stats["removed"] += 1
