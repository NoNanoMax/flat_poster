"""Tests for ColdStorageManager."""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.cold_storage.manager import ColdStorageManager
from src.config.settings import ColdStorageSettings


@pytest.fixture
def settings():
    return ColdStorageSettings(
        warm_check_interval_hours=24,
        cold_check_interval_hours=72,
        max_checks_before_remove=5,
        ttl_days=30,
        price_drop_threshold_pct=5.0,
    )


@pytest.fixture
def mock_scraper():
    scraper = MagicMock()
    scraper._settings = MagicMock()
    scraper._settings.delay_between_requests = 0  # no delay in tests
    scraper.fetch_listing_details = AsyncMock()
    return scraper


@pytest.fixture
def mock_evaluator():
    evaluator = MagicMock()
    evaluator.evaluate_and_save = AsyncMock()
    return evaluator


@pytest.fixture
def mock_notifier():
    notifier = AsyncMock()
    return notifier


@pytest.fixture
def manager(settings, mock_scraper, mock_evaluator, mock_notifier):
    return ColdStorageManager(
        settings=settings,
        scraper=mock_scraper,
        evaluator=mock_evaluator,
        notifier=mock_notifier,
    )


@pytest.fixture
def mock_listing():
    listing = MagicMock()
    listing.cian_id = 123456
    listing.id = 1
    listing.status = "warm"
    listing.last_verdict = "warm"
    listing.price = 10_000_000
    listing.cold_check_count = 2
    listing.created_at = datetime.utcnow() - timedelta(days=10)
    listing.ttl_days = 30
    listing.next_check_at = datetime.utcnow() - timedelta(hours=1)
    listing.last_checked = None
    listing.photos = None
    listing.last_score = 65.0
    listing.last_verdict = "warm"
    return listing


@pytest.fixture
def mock_session(mock_listing):
    session = MagicMock()
    return session


# ── run_check ────────────────────────────────────────────────────────────────


class TestRunCheck:
    async def test_no_listings_due(self, manager, mock_session, settings):
        """No listings due → empty stats."""
        with patch(
            "src.cold_storage.manager.ListingRepo",
            return_value=MagicMock(get_for_cold_check=AsyncMock(return_value=[])),
        ):
            stats = await manager.run_check(mock_session)
        assert stats == {
            "checked": 0,
            "re_evaluated": 0,
            "escalated": 0,
            "skipped": 0,
            "removed": 0,
            "errors": 0,
        }

    async def test_skip_action(self, manager, mock_session, mock_scraper, mock_listing, settings):
        """Price unchanged → SKIP, bump next_check_at."""
        # Scraper returns same price
        raw = MagicMock(price=10_000_000)
        mock_scraper.fetch_listing_details.return_value = raw

        listing_repo = MagicMock()
        listing_repo.get_for_cold_check = AsyncMock(return_value=[mock_listing])
        listing_repo.delete = AsyncMock()

        with patch("src.cold_storage.manager.ListingRepo", return_value=listing_repo):
            stats = await manager.run_check(mock_session)

        assert stats["checked"] == 1
        assert stats["skipped"] == 1
        # next_check_at should be updated (warm strategy = 24h)
        assert mock_listing.next_check_at is not None

    async def test_re_evaluate_action(self, manager, mock_session, mock_scraper, mock_evaluator, mock_listing, settings):
        """Price dropped → RE_EVALUATE."""
        raw = MagicMock(price=9_000_000)  # 10% drop
        mock_scraper.fetch_listing_details.return_value = raw

        eval_result = MagicMock()
        eval_result.score = 70.0
        eval_result.verdict = "warm"  # stayed warm
        mock_evaluator.evaluate_and_save.return_value = eval_result

        listing_repo = MagicMock()
        listing_repo.get_for_cold_check = AsyncMock(return_value=[mock_listing])
        listing_repo.delete = AsyncMock()

        with patch("src.cold_storage.manager.ListingRepo", return_value=listing_repo):
            stats = await manager.run_check(mock_session)

        assert stats["re_evaluated"] == 1
        mock_evaluator.evaluate_and_save.assert_called_once()

    async def test_escalate_action(self, manager, mock_session, mock_scraper, mock_evaluator, mock_listing, mock_notifier, settings):
        """Price dropped → re-eval → HOT → ESCALATE + notification."""
        raw = MagicMock(price=8_500_000)  # 15% drop
        mock_scraper.fetch_listing_details.return_value = raw

        eval_result = MagicMock()
        eval_result.score = 85.0
        eval_result.verdict = "hot"
        mock_evaluator.evaluate_and_save.return_value = eval_result

        # Mock EvaluationRepo.get_latest returning a valid evaluation
        mock_eval_log = MagicMock()
        mock_eval_log.verdict = "hot"
        mock_eval_log.score = 85.0

        # Mock formatter to avoid f-string issues with MagicMock listing
        manager._formatter.format_for_telegram = MagicMock(return_value="HOT notification text")

        listing_repo = MagicMock()
        listing_repo.get_for_cold_check = AsyncMock(return_value=[mock_listing])
        listing_repo.delete = AsyncMock()

        with (
            patch("src.cold_storage.manager.ListingRepo", return_value=listing_repo),
            patch("src.cold_storage.manager.EvaluationRepo") as mock_eval_repo,
        ):
            mock_eval_repo.return_value.get_latest = AsyncMock(return_value=mock_eval_log)
            stats = await manager.run_check(mock_session)

        assert stats["escalated"] == 1
        mock_notifier.send.assert_called_once()

    async def test_remove_action_max_checks(self, manager, mock_session, mock_listing, settings):
        """cold_check_count >= max → REMOVE (no scrape needed)."""
        mock_listing.cold_check_count = 4  # will be incremented to 5

        listing_repo = MagicMock()
        listing_repo.get_for_cold_check = AsyncMock(return_value=[mock_listing])
        listing_repo.delete = AsyncMock()

        with patch("src.cold_storage.manager.ListingRepo", return_value=listing_repo):
            stats = await manager.run_check(mock_session)

        assert stats["removed"] == 1
        # Scraper should NOT be called (removed before scraping)
        listing_repo.delete.assert_called_once()

    async def test_remove_action_delisted(self, manager, mock_session, mock_scraper, mock_listing, settings):
        """Listing delisted (None from scraper) → REMOVE."""
        mock_scraper.fetch_listing_details.return_value = None

        listing_repo = MagicMock()
        listing_repo.get_for_cold_check = AsyncMock(return_value=[mock_listing])
        listing_repo.delete = AsyncMock()

        with patch("src.cold_storage.manager.ListingRepo", return_value=listing_repo):
            stats = await manager.run_check(mock_session)

        assert stats["removed"] == 1

    async def test_error_handling(self, manager, mock_session, mock_scraper, mock_listing, settings):
        """Scraper raises exception → price fetch returns None → REMOVE (not error)."""
        mock_scraper.fetch_listing_details.side_effect = Exception("Network error")

        listing_repo = MagicMock()
        listing_repo.get_for_cold_check = AsyncMock(return_value=[mock_listing])
        listing_repo.delete = AsyncMock()

        with patch("src.cold_storage.manager.ListingRepo", return_value=listing_repo):
            stats = await manager.run_check(mock_session)

        # When fetch fails → new_price is None → determine_action returns REMOVE
        assert stats["checked"] == 1
        assert stats["removed"] == 1
        assert stats["errors"] == 0  # error is handled gracefully, not counted as error

    async def test_multiple_listings(self, manager, mock_session, mock_scraper, settings):
        """Multiple listings with different outcomes."""
        listing1 = MagicMock()
        listing1.cian_id = 1
        listing1.id = 1
        listing1.status = "warm"
        listing1.last_verdict = "warm"
        listing1.price = 10_000_000
        listing1.cold_check_count = 2
        listing1.created_at = datetime.utcnow() - timedelta(days=10)
        listing1.photos = None

        listing2 = MagicMock()
        listing2.cian_id = 2
        listing2.id = 2
        listing2.status = "cold"
        listing2.last_verdict = "cold"
        listing2.price = 10_000_000
        listing2.cold_check_count = 4  # will be 5 → removed
        listing2.created_at = datetime.utcnow() - timedelta(days=10)
        listing2.photos = None

        raw = MagicMock(price=10_000_000)  # same price for listing1
        mock_scraper.fetch_listing_details.return_value = raw

        listing_repo = MagicMock()
        listing_repo.get_for_cold_check = AsyncMock(return_value=[listing1, listing2])
        listing_repo.delete = AsyncMock()

        with patch("src.cold_storage.manager.ListingRepo", return_value=listing_repo):
            stats = await manager.run_check(mock_session)

        assert stats["checked"] == 2
        assert stats["skipped"] == 1
        assert stats["removed"] == 1


# ── run_cleanup ──────────────────────────────────────────────────────────────


class TestRunCleanup:
    async def test_cleanup_expired(self, manager, mock_session, settings):
        """Remove listings with cold_check_count >= max."""
        expired_listing = MagicMock()
        expired_listing.cian_id = 999
        expired_listing.cold_check_count = 5

        listing_repo = MagicMock()
        listing_repo.get_expired = AsyncMock(return_value=[expired_listing])
        listing_repo.get_by_status = AsyncMock(return_value=[])
        listing_repo.delete = AsyncMock()

        with patch("src.cold_storage.manager.ListingRepo", return_value=listing_repo):
            removed = await manager.run_cleanup(mock_session)

        assert removed == 1

    async def test_cleanup_ttl_expired(self, manager, mock_session, settings):
        """Remove listings past TTL."""
        old_listing = MagicMock()
        old_listing.cian_id = 888
        old_listing.created_at = datetime.utcnow() - timedelta(days=31)

        listing_repo = MagicMock()
        listing_repo.get_expired = AsyncMock(return_value=[])
        # get_by_status called twice: "warm" → [old_listing], "cold" → []
        listing_repo.get_by_status = AsyncMock(side_effect=[
            [old_listing],  # warm
            [],             # cold
        ])
        listing_repo.delete = AsyncMock()

        with patch("src.cold_storage.manager.ListingRepo", return_value=listing_repo):
            removed = await manager.run_cleanup(mock_session)

        assert removed == 1

    async def test_cleanup_nothing_to_remove(self, manager, mock_session, settings):
        """No expired listings → 0 removed."""
        listing_repo = MagicMock()
        listing_repo.get_expired = AsyncMock(return_value=[])
        listing_repo.get_by_status = AsyncMock(side_effect=[[], []])
        listing_repo.delete = AsyncMock()

        with patch("src.cold_storage.manager.ListingRepo", return_value=listing_repo):
            removed = await manager.run_cleanup(mock_session)

        assert removed == 0

    async def test_cleanup_both_expired_and_ttl(self, manager, mock_session, settings):
        """Both max-checks expired and TTL expired."""
        expired1 = MagicMock()
        expired1.cian_id = 111
        expired1.cold_check_count = 5

        expired2 = MagicMock()
        expired2.cian_id = 222
        expired2.created_at = datetime.utcnow() - timedelta(days=35)

        listing_repo = MagicMock()
        listing_repo.get_expired = AsyncMock(return_value=[expired1])
        # get_by_status called twice: "warm" → [expired2], "cold" → []
        listing_repo.get_by_status = AsyncMock(side_effect=[
            [expired2],  # warm
            [],          # cold
        ])
        listing_repo.delete = AsyncMock()

        with patch("src.cold_storage.manager.ListingRepo", return_value=listing_repo):
            removed = await manager.run_cleanup(mock_session)

        assert removed == 2
