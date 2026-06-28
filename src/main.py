"""Main entry point — initialise DB, load seed queries, then start scheduler."""

from __future__ import annotations

import asyncio
import signal
import sys

from loguru import logger

from src.config.queries import load_search_queries
from src.config.settings import settings
from src.db.engine import close_db, init_db, session_scope
from src.db.repository import SearchQueryRepo
from src.scheduler.runner import SchedulerRunner

# Global reference for signal handler
_runner: SchedulerRunner | None = None


async def seed_queries() -> None:
    """Load YAML queries into DB if not already present."""
    yaml_queries = load_search_queries()
    async with session_scope() as session:
        repo = SearchQueryRepo(session)
        count = await repo.seed_from_yaml(yaml_queries)
    logger.info("Seeded {} new queries from YAML", count)


async def main() -> None:
    global _runner

    logger.info("═══════════════════════════════════════════")
    logger.info("  Flat Parser — starting up")
    logger.info("═══════════════════════════════════════════")

    # 1. Init DB
    await init_db()
    logger.info("Database initialised: {}", settings.database.url)

    # 2. Seed queries from YAML
    await seed_queries()

    # 3. Start scheduler
    _runner = SchedulerRunner()
    _runner.start()

    # 4. Wait forever — scheduler runs in background
    logger.info("All systems running. Press Ctrl+C to stop.")
    await asyncio.Event().wait()


def setup_logging() -> None:
    """Configure loguru logging."""
    log_cfg = settings.logging

    logger.remove()  # remove default

    # Console
    logger.add(
        sys.stderr,
        level=log_cfg.level,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
        "<level>{message}</level>",
    )

    # File
    logger.add(
        log_cfg.file,
        level=log_cfg.level,
        rotation=log_cfg.rotation,
        retention=log_cfg.retention,
        encoding="utf-8",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} | {message}",
    )


if __name__ == "__main__":
    setup_logging()

    loop = asyncio.new_event_loop()

    # Graceful shutdown on SIGINT/SIGTERM
    def _shutdown(sig: int, frame):  # type: ignore[no-untyped-def]
        if _runner:
            _runner.shutdown()
        loop.stop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, _shutdown)

    loop.run_until_complete(main())
    loop.run_until_complete(close_db())
