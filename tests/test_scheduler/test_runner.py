"""Tests for SchedulerRunner."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


class TestSchedulerRunner:
    @pytest.fixture
    def mock_settings(self):
        with patch("src.scheduler.runner.settings") as mock_set:
            mock_set.scheduler.fetch_listings_interval_min = 60
            mock_set.scheduler.fetch_details_interval_min = 15
            mock_set.scheduler.evaluate_new_interval_min = 20
            mock_set.scheduler.check_cold_storage_interval_min = 120
            mock_set.scheduler.cleanup_interval_hours = 24
            yield mock_set

    def test_init(self):
        """SchedulerRunner creates AsyncIOScheduler."""
        from src.scheduler.runner import SchedulerRunner

        runner = SchedulerRunner()
        assert runner._scheduler is not None

    def test_start_registers_jobs(self, mock_settings):
        """start() registers all 5 jobs."""
        with patch("src.scheduler.runner.AsyncIOScheduler") as mock_scheduler_cls:
            mock_sched = MagicMock()
            mock_scheduler_cls.return_value = mock_sched
            mock_sched.get_jobs.return_value = []

            from src.scheduler.runner import SchedulerRunner

            runner = SchedulerRunner()
            runner.start()

            # 5 jobs registered
            assert mock_sched.add_job.call_count == 5
            mock_sched.start.assert_called_once()

    def test_start_registers_fetch_listings(self, mock_settings):
        """fetch_listings job registered with correct interval."""
        with patch("src.scheduler.runner.AsyncIOScheduler") as mock_scheduler_cls:
            mock_sched = MagicMock()
            mock_scheduler_cls.return_value = mock_sched
            mock_sched.get_jobs.return_value = []

            from src.scheduler.runner import SchedulerRunner

            runner = SchedulerRunner()
            runner.start()

            # First call should be fetch_listings
            first_call = mock_sched.add_job.call_args_list[0]
            assert first_call[0][1] == "interval"
            assert first_call[1]["minutes"] == 60
            assert first_call[1]["id"] == "fetch_listings"

    def test_start_registers_fetch_details(self, mock_settings):
        """fetch_details job registered with correct interval."""
        with patch("src.scheduler.runner.AsyncIOScheduler") as mock_scheduler_cls:
            mock_sched = MagicMock()
            mock_scheduler_cls.return_value = mock_sched
            mock_sched.get_jobs.return_value = []

            from src.scheduler.runner import SchedulerRunner

            runner = SchedulerRunner()
            runner.start()

            # Second call should be fetch_details
            second_call = mock_sched.add_job.call_args_list[1]
            assert second_call[0][1] == "interval"
            assert second_call[1]["minutes"] == 15
            assert second_call[1]["id"] == "fetch_details"

    def test_start_registers_evaluate_new(self, mock_settings):
        """evaluate_new job registered with correct interval."""
        with patch("src.scheduler.runner.AsyncIOScheduler") as mock_scheduler_cls:
            mock_sched = MagicMock()
            mock_scheduler_cls.return_value = mock_sched
            mock_sched.get_jobs.return_value = []

            from src.scheduler.runner import SchedulerRunner

            runner = SchedulerRunner()
            runner.start()

            third_call = mock_sched.add_job.call_args_list[2]
            assert third_call[0][1] == "interval"
            assert third_call[1]["minutes"] == 20
            assert third_call[1]["id"] == "evaluate_new"

    def test_start_registers_cold_storage(self, mock_settings):
        """check_cold_storage job registered with correct interval."""
        with patch("src.scheduler.runner.AsyncIOScheduler") as mock_scheduler_cls:
            mock_sched = MagicMock()
            mock_scheduler_cls.return_value = mock_sched
            mock_sched.get_jobs.return_value = []

            from src.scheduler.runner import SchedulerRunner

            runner = SchedulerRunner()
            runner.start()

            fourth_call = mock_sched.add_job.call_args_list[3]
            assert fourth_call[0][1] == "interval"
            assert fourth_call[1]["minutes"] == 120
            assert fourth_call[1]["id"] == "check_cold_storage"

    def test_start_registers_cleanup(self, mock_settings):
        """cleanup job registered with correct interval (hours)."""
        with patch("src.scheduler.runner.AsyncIOScheduler") as mock_scheduler_cls:
            mock_sched = MagicMock()
            mock_scheduler_cls.return_value = mock_sched
            mock_sched.get_jobs.return_value = []

            from src.scheduler.runner import SchedulerRunner

            runner = SchedulerRunner()
            runner.start()

            fifth_call = mock_sched.add_job.call_args_list[4]
            assert fifth_call[0][1] == "interval"
            assert fifth_call[1]["hours"] == 24
            assert fifth_call[1]["id"] == "cleanup"

    def test_shutdown_stops_scheduler(self):
        """shutdown() calls scheduler.shutdown."""
        with patch("src.scheduler.runner.AsyncIOScheduler") as mock_scheduler_cls:
            mock_sched = MagicMock()
            mock_scheduler_cls.return_value = mock_sched

            from src.scheduler.runner import SchedulerRunner

            runner = SchedulerRunner()
            runner.shutdown()

            mock_sched.shutdown.assert_called_once_with(wait=False)

    def test_custom_intervals(self):
        """Custom intervals from settings are respected."""
        with patch("src.scheduler.runner.settings") as mock_set:
            mock_set.scheduler.fetch_listings_interval_min = 30
            mock_set.scheduler.fetch_details_interval_min = 5
            mock_set.scheduler.evaluate_new_interval_min = 10
            mock_set.scheduler.check_cold_storage_interval_min = 60
            mock_set.scheduler.cleanup_interval_hours = 12

            with patch("src.scheduler.runner.AsyncIOScheduler") as mock_scheduler_cls:
                mock_sched = MagicMock()
                mock_scheduler_cls.return_value = mock_sched
                mock_sched.get_jobs.return_value = []

                from src.scheduler.runner import SchedulerRunner

                runner = SchedulerRunner()
                runner.start()

                # Check first job interval
                first_call = mock_sched.add_job.call_args_list[0]
                assert first_call[1]["minutes"] == 30

                # Check last job interval
                last_call = mock_sched.add_job.call_args_list[4]
                assert last_call[1]["hours"] == 12
