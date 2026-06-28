"""Cold storage strategies — determine what to do with each listing on re-check."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum

from loguru import logger

from src.config.settings import ColdStorageSettings
from src.db.models import Listing


class CheckAction(Enum):
    """Possible actions when re-checking a cold-storage listing."""

    RE_EVALUATE = "re_evaluate"  # price dropped significantly → re-evaluate via LLM
    SKIP = "skip"  # price stable → just bump next_check_at
    ESCALATE = "escalate"  # re-evaluated and became hot → notify
    REMOVE = "remove"  # expired / too many checks / delisted


@dataclass
class CheckResult:
    """Result of checking a single listing."""

    cian_id: int
    action: CheckAction
    new_price: int | None = None
    old_price: int | None = None
    re_eval_score: float | None = None
    re_eval_verdict: str | None = None


# ── Strategy base ────────────────────────────────────────────────────────────


class Strategy:
    """Base strategy for cold-storage checks."""

    check_interval_hours: int = 24

    def next_check_at(self, listing: Listing) -> datetime:
        """Compute next_check_at for a listing under this strategy."""
        return datetime.utcnow() + timedelta(hours=self.check_interval_hours)


class WarmStrategy(Strategy):
    """WARM listings (score 60-79): check every 24 hours."""

    check_interval_hours = 24


class ColdStrategy(Strategy):
    """COLD listings (score 40-59): check every 72 hours."""

    check_interval_hours = 72


# ── Removal logic ────────────────────────────────────────────────────────────


class RemovalStrategy:
    """Rules for removing listings from cold storage."""

    def should_remove(self, listing: Listing, settings: ColdStorageSettings) -> bool:
        """Return True if the listing should be removed regardless of price."""
        # Too many checks without improvement
        if listing.cold_check_count >= settings.max_checks_before_remove:
            logger.info(
                "Removing cian_id={}: exceeded max checks ({})",
                listing.cian_id,
                settings.max_checks_before_remove,
            )
            return True

        # TTL expired
        if listing.created_at:
            ttl = timedelta(days=settings.ttl_days)
            if datetime.utcnow() >= listing.created_at + ttl:
                logger.info(
                    "Removing cian_id={}: TTL of {} days expired",
                    listing.cian_id,
                    settings.ttl_days,
                )
                return True

        return False


# ── Action determination ────────────────────────────────────────────────────


def determine_action(
    listing: Listing,
    new_price: int | None,
    settings: ColdStorageSettings,
) -> CheckAction:
    """Decide what to do with a listing based on its state and the scraped price.

    Order of checks:
    1. RemovalStrategy (max checks, TTL)
    2. Delisted (new_price is None)
    3. Price dropped beyond threshold
    4. Otherwise: skip (just bump next_check_at)
    """
    removal = RemovalStrategy()

    # 1. Check removal rules
    if removal.should_remove(listing, settings):
        return CheckAction.REMOVE

    # 2. Delisted — price is None means we couldn't fetch or it's gone
    if new_price is None:
        logger.info("Removing cian_id={}: delisted or fetch failed", listing.cian_id)
        return CheckAction.REMOVE

    # 3. Price drop check
    if listing.price and listing.price > 0:
        drop_pct = (listing.price - new_price) / listing.price * 100
        if drop_pct >= settings.price_drop_threshold_pct:
            logger.info(
                "Price drop on cian_id={}: {:.1f}% (threshold {:.1f}%) → re-evaluate",
                listing.cian_id,
                drop_pct,
                settings.price_drop_threshold_pct,
            )
            return CheckAction.RE_EVALUATE

    # 4. Stable — just bump the timer
    return CheckAction.SKIP


# ── Strategy lookup ──────────────────────────────────────────────────────────


def get_strategy_for_verdict(verdict: str) -> Strategy:
    """Return the appropriate strategy based on the listing's current verdict."""
    if verdict == "warm":
        return WarmStrategy()
    if verdict == "cold":
        return ColdStrategy()
    # Fallback: treat unknown as warm
    return WarmStrategy()
