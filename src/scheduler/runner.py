"""Scheduler runner — wraps APScheduler with our jobs and graceful shutdown."""

from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from loguru import logger

from src.config.settings import settings
from src.scheduler.jobs import (
    check_cold_storage_job,
    cleanup_job,
    evaluate_new_job,
    fetch_details_job,
    fetch_listings_job,
)


class SchedulerRunner:
    """Wraps APScheduler with our jobs and graceful shutdown.

    Jobs are registered from settings.yaml intervals and run in the same event loop.
    """

    def __init__(self) -> None:
        self._scheduler = AsyncIOScheduler()

    def start(self) -> None:
        """Register all jobs and start the scheduler."""
        self._register_jobs()
        self._scheduler.start()
        logger.info("Scheduler started with {} jobs", len(self._scheduler.get_jobs()))

    def _register_jobs(self) -> None:
        """Register all scheduled jobs based on settings."""
        sched = settings.scheduler

        self._scheduler.add_job(
            fetch_listings_job,
            "interval",
            minutes=sched.fetch_listings_interval_min,
            id="fetch_listings",
            name="Fetch new listings from Cian",
        )
        logger.info(
            "Registered job: fetch_listings every {} min",
            sched.fetch_listings_interval_min,
        )

        self._scheduler.add_job(
            fetch_details_job,
            "interval",
            minutes=sched.fetch_details_interval_min,
            id="fetch_details",
            name="Fetch listing details",
        )
        logger.info(
            "Registered job: fetch_details every {} min",
            sched.fetch_details_interval_min,
        )

        self._scheduler.add_job(
            evaluate_new_job,
            "interval",
            minutes=sched.evaluate_new_interval_min,
            id="evaluate_new",
            name="Evaluate new listings via LLM",
        )
        logger.info(
            "Registered job: evaluate_new every {} min",
            sched.evaluate_new_interval_min,
        )

        self._scheduler.add_job(
            check_cold_storage_job,
            "interval",
            minutes=sched.check_cold_storage_interval_min,
            id="check_cold_storage",
            name="Re-check cold storage",
        )
        logger.info(
            "Registered job: check_cold_storage every {} min",
            sched.check_cold_storage_interval_min,
        )

        self._scheduler.add_job(
            cleanup_job,
            "interval",
            hours=sched.cleanup_interval_hours,
            id="cleanup",
            name="Cleanup expired listings",
        )
        logger.info(
            "Registered job: cleanup every {} hours",
            sched.cleanup_interval_hours,
        )

    def shutdown(self) -> None:
        """Graceful shutdown — stop the scheduler."""
        self._scheduler.shutdown(wait=False)
        logger.info("Scheduler shut down")
