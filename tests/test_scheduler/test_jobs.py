"""Tests for scheduler jobs."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.config.settings import settings


@pytest.fixture
def mock_settings():
    """Return settings with test_mode=True (ConsoleNotifier)."""
    return settings


class TestGetNotifier:
    def test_returns_console_in_test_mode(self):
        """test_mode=True → ConsoleNotifier."""
        with patch("src.scheduler.jobs.settings") as mock_set:
            mock_set.telegram.test_mode = True
            mock_set.telegram.token = ""
            from src.scheduler.jobs import _get_notifier

            notifier = _get_notifier()
            from src.notifier.console import ConsoleNotifier

            assert isinstance(notifier, ConsoleNotifier)

    def test_returns_telegram_in_production(self):
        """test_mode=False + token set → TelegramNotifier."""
        with patch("src.scheduler.jobs.settings") as mock_set:
            mock_set.telegram.test_mode = False
            mock_set.telegram.token = "fake:token"
            mock_set.telegram.channel_id = "-123"
            with patch("src.scheduler.jobs.TelegramNotifier") as mock_tg:
                from src.scheduler.jobs import _get_notifier

                notifier = _get_notifier()
                mock_tg.assert_called_once()
                assert notifier is mock_tg.return_value


class TestFetchListingsJob:
    async def test_no_enabled_queries(self):
        """No enabled queries → early return."""
        with patch("src.scheduler.jobs.session_scope") as mock_scope:
            session = MagicMock()
            mock_scope.return_value.__aenter__ = AsyncMock(return_value=session)
            mock_scope.return_value.__aexit__ = AsyncMock(return_value=False)

            query_repo = MagicMock()
            query_repo.get_enabled = AsyncMock(return_value=[])
            with patch("src.scheduler.jobs.SearchQueryRepo", return_value=query_repo):
                from src.scheduler.jobs import fetch_listings_job

                await fetch_listings_job()

            query_repo.get_enabled.assert_called_once()

    async def test_fetches_new_listings(self):
        """Fetch new listings and upsert them."""
        with patch("src.scheduler.jobs.session_scope") as mock_scope:
            session = MagicMock()
            mock_scope.return_value.__aenter__ = AsyncMock(return_value=session)
            mock_scope.return_value.__aexit__ = AsyncMock(return_value=False)

            query_repo = MagicMock()
            mock_query = MagicMock()
            mock_query.name = "test query"
            query_repo.get_enabled = AsyncMock(return_value=[mock_query])

            listing_repo = MagicMock()
            listing_repo.get_by_cian_id = AsyncMock(return_value=None)
            listing_repo.upsert = AsyncMock()

            mock_brief = MagicMock()
            mock_brief.cian_id = 999
            mock_brief.to_dict = MagicMock(return_value={"cian_id": 999, "title": "Test"})

            mock_scraper = MagicMock()
            mock_scraper.fetch_search_page = AsyncMock(return_value=[mock_brief])

            with (
                patch("src.scheduler.jobs.SearchQueryRepo", return_value=query_repo),
                patch("src.scheduler.jobs.ListingRepo", return_value=listing_repo),
                patch("src.scheduler.jobs.CianScraper", return_value=mock_scraper),
            ):
                from src.scheduler.jobs import fetch_listings_job

                await fetch_listings_job()

            listing_repo.upsert.assert_called_once()
            call_args = listing_repo.upsert.call_args[0][0]
            assert call_args["status"] == "new"


class TestFetchDetailsJob:
    async def test_no_new_listings(self):
        """No new listings → early return."""
        with patch("src.scheduler.jobs.session_scope") as mock_scope:
            session = MagicMock()
            mock_scope.return_value.__aenter__ = AsyncMock(return_value=session)
            mock_scope.return_value.__aexit__ = AsyncMock(return_value=False)

            listing_repo = MagicMock()
            listing_repo.get_by_status = AsyncMock(return_value=[])

            with patch("src.scheduler.jobs.ListingRepo", return_value=listing_repo):
                from src.scheduler.jobs import fetch_details_job

                await fetch_details_job()

            listing_repo.get_by_status.assert_called_once_with("new")

    async def test_fetches_details_for_pending(self):
        """Fetch details for listings with area=None."""
        with patch("src.scheduler.jobs.session_scope") as mock_scope:
            session = MagicMock()
            mock_scope.return_value.__aenter__ = AsyncMock(return_value=session)
            mock_scope.return_value.__aexit__ = AsyncMock(return_value=False)

            mock_listing = MagicMock()
            mock_listing.cian_id = 123
            mock_listing.area = None

            listing_repo = MagicMock()
            listing_repo.get_by_status = AsyncMock(return_value=[mock_listing])
            listing_repo.upsert = AsyncMock()

            mock_details = MagicMock()
            mock_details.to_dict = MagicMock(return_value={"cian_id": 123, "area": 50.0})

            mock_scraper = MagicMock()
            mock_scraper.fetch_listing_details = AsyncMock(return_value=mock_details)

            with (
                patch("src.scheduler.jobs.ListingRepo", return_value=listing_repo),
                patch("src.scheduler.jobs.CianScraper", return_value=mock_scraper),
            ):
                from src.scheduler.jobs import fetch_details_job

                await fetch_details_job()

            mock_scraper.fetch_listing_details.assert_called_once_with(123, brief=None)
            listing_repo.upsert.assert_called_once()


class TestEvaluateNewJob:
    async def test_no_results(self):
        """No evaluation results → early return."""
        with patch("src.scheduler.jobs.session_scope") as mock_scope:
            session = MagicMock()
            mock_scope.return_value.__aenter__ = AsyncMock(return_value=session)
            mock_scope.return_value.__aexit__ = AsyncMock(return_value=False)

            mock_evaluator = MagicMock()
            mock_evaluator.evaluate_batch = AsyncMock(return_value=[])

            with (
                patch("src.scheduler.jobs.EvaluationAgent", return_value=mock_evaluator),
                patch("src.scheduler.jobs.LLMClient"),
            ):
                from src.scheduler.jobs import evaluate_new_job

                await evaluate_new_job()

            mock_evaluator.evaluate_batch.assert_called_once()

    async def test_sends_notifications_for_hot(self):
        """Hot listings → send notifications."""
        with patch("src.scheduler.jobs.session_scope") as mock_scope:
            session = MagicMock()
            mock_scope.return_value.__aenter__ = AsyncMock(return_value=session)
            mock_scope.return_value.__aexit__ = AsyncMock(return_value=False)

            mock_evaluator = MagicMock()
            mock_result = MagicMock()
            mock_result.score = 85.0
            mock_result.verdict = "hot"
            mock_evaluator.evaluate_batch = AsyncMock(return_value=[mock_result])

            mock_listing = MagicMock()
            mock_listing.id = 1
            mock_listing.cian_id = 999
            mock_listing.photos = None
            mock_listing.last_score = 85.0
            mock_listing.last_verdict = "hot"

            listing_repo = MagicMock()
            listing_repo.get_by_status = AsyncMock(return_value=[mock_listing])

            mock_eval_log = MagicMock()
            mock_eval_log.verdict = "hot"
            mock_eval_log.score = 85.0
            mock_eval_log.reasoning = "Great deal"
            mock_eval_log.pros_list = ["Good price"]
            mock_eval_log.cons_list = []
            mock_eval_log.price_assessment = "cheap"
            mock_eval_log.price_vs_market_pct = -15.0
            mock_eval_log.location_score = 90.0
            mock_eval_log.quality_score = 80.0
            mock_eval_log.investment_score = 85.0

            eval_repo = MagicMock()
            eval_repo.get_latest = AsyncMock(return_value=mock_eval_log)

            mock_notifier = AsyncMock()

            with (
                patch("src.scheduler.jobs.EvaluationAgent", return_value=mock_evaluator),
                patch("src.scheduler.jobs.LLMClient"),
                patch("src.scheduler.jobs.ListingRepo", return_value=listing_repo),
                patch("src.scheduler.jobs.EvaluationRepo", return_value=eval_repo),
                patch("src.scheduler.jobs._get_notifier", return_value=mock_notifier),
                patch("src.scheduler.jobs.ListingFormatter"),
            ):
                from src.scheduler.jobs import evaluate_new_job

                await evaluate_new_job()

            mock_notifier.send.assert_called()


class TestCheckColdStorageJob:
    async def test_calls_manager_run_check(self):
        """Job calls ColdStorageManager.run_check."""
        with patch("src.scheduler.jobs.session_scope") as mock_scope:
            session = MagicMock()
            mock_scope.return_value.__aenter__ = AsyncMock(return_value=session)
            mock_scope.return_value.__aexit__ = AsyncMock(return_value=False)

            mock_manager = MagicMock()
            mock_manager.run_check = AsyncMock(return_value={"checked": 5, "skipped": 3})

            mock_notifier = AsyncMock()

            with (
                patch("src.scheduler.jobs.ColdStorageManager", return_value=mock_manager),
                patch("src.scheduler.jobs.CianScraper"),
                patch("src.scheduler.jobs.LLMClient"),
                patch("src.scheduler.jobs.EvaluationAgent"),
                patch("src.scheduler.jobs._get_notifier", return_value=mock_notifier),
                patch("src.scheduler.jobs.settings") as mock_set,
            ):
                mock_set.cold_storage = MagicMock()
                from src.scheduler.jobs import check_cold_storage_job

                await check_cold_storage_job()

            mock_manager.run_check.assert_called_once_with(session)


class TestCleanupJob:
    async def test_calls_manager_run_cleanup(self):
        """Job calls ColdStorageManager.run_cleanup."""
        with patch("src.scheduler.jobs.session_scope") as mock_scope:
            session = MagicMock()
            mock_scope.return_value.__aenter__ = AsyncMock(return_value=session)
            mock_scope.return_value.__aexit__ = AsyncMock(return_value=False)

            mock_manager = MagicMock()
            mock_manager.run_cleanup = AsyncMock(return_value=3)

            mock_notifier = AsyncMock()

            with (
                patch("src.scheduler.jobs.ColdStorageManager", return_value=mock_manager),
                patch("src.scheduler.jobs.CianScraper"),
                patch("src.scheduler.jobs.LLMClient"),
                patch("src.scheduler.jobs.EvaluationAgent"),
                patch("src.scheduler.jobs._get_notifier", return_value=mock_notifier),
                patch("src.scheduler.jobs.settings") as mock_set,
            ):
                mock_set.cold_storage = MagicMock()
                from src.scheduler.jobs import cleanup_job

                await cleanup_job()

            mock_manager.run_cleanup.assert_called_once_with(session)
