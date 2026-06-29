"""Async SQLAlchemy engine and session factory."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.config.settings import settings
from src.db.models import Base

# SQLite doesn't support pool_size; only set for PostgreSQL
_engine_kwargs: dict[str, object] = {
    "echo": settings.logging.level == "DEBUG",
}
if "sqlite" not in settings.database.url:
    _engine_kwargs["pool_size"] = 5
    _engine_kwargs["max_overflow"] = 10

# Create engine
engine = create_async_engine(settings.database.url, **_engine_kwargs)

# Session factory
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@asynccontextmanager
async def session_scope() -> AsyncGenerator[AsyncSession, None]:
    """Context manager for async DB sessions. Auto-commits on success, rollback on error."""
    session = async_session()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def init_db():
    """Create all tables. Safe to call multiple times."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def close_db():
    """Close engine connections."""
    await engine.dispose()
