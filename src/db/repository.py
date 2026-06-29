"""CRUD repositories for database operations."""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import datetime, timezone

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import EvaluationLog, Listing, MarketStat, SearchQuery

# ── ListingRepository ────────────────────────────────────────────────────────


class ListingRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_cian_id(self, cian_id: int) -> Listing | None:
        """Get listing by Cian ID."""
        result = await self.session.execute(select(Listing).where(Listing.cian_id == cian_id))
        return result.scalar_one_or_none()

    async def upsert(self, data: dict) -> Listing:
        """Insert or update a listing by cian_id.

        Args:
            data: dict with listing fields (cian_id required).

        Returns:
            The Listing instance (new or updated).
        """
        cian_id = data["cian_id"]
        existing = await self.get_by_cian_id(cian_id)

        if existing:
            # Update price if changed
            new_price = data.get("price", existing.price)
            if new_price != existing.price:
                # Append to history
                history = json.loads(existing.price_history) if existing.price_history else []  # type: ignore[arg-type]
                history.append({"date": datetime.now(timezone.utc).isoformat(), "price": existing.price})
                existing.price = new_price
                existing.price_history = json.dumps(history, ensure_ascii=False)

            # Update all other fields
            for key, value in data.items():
                if key != "cian_id" and value is not None:
                    setattr(existing, key, value)
            existing.last_checked = datetime.now(timezone.utc)
        else:
            # New listing
            existing = Listing(**data)

        if existing.area and existing.area > 0:
            existing.price_per_sqm = round(existing.price / existing.area, 2)

        self.session.add(existing)
        return existing

    async def get_by_status(self, status: str, limit: int = 100) -> Sequence[Listing]:
        """Get listings by status."""
        result = await self.session.execute(select(Listing).where(Listing.status == status).limit(limit))
        return result.scalars().all()

    async def get_pending_evaluation(self, limit: int = 20) -> Sequence[Listing]:
        """Get new listings that need evaluation."""
        result = await self.session.execute(
            select(Listing).where(Listing.status == "new").order_by(Listing.created_at.desc()).limit(limit)
        )
        return result.scalars().all()

    async def set_status(self, cian_id: int, status: str) -> Listing | None:
        """Update listing status."""
        listing = await self.get_by_cian_id(cian_id)
        if listing:
            listing.status = status
            self.session.add(listing)
        return listing

    async def get_for_cold_check(self) -> Sequence[Listing]:
        """Get warm/cold listings due for re-check."""
        now = datetime.now(timezone.utc)
        result = await self.session.execute(
            select(Listing).where(
                and_(
                    Listing.status.in_(["warm", "cold"]),
                    Listing.next_check_at <= now,
                )
            )
        )
        return result.scalars().all()

    async def get_expired(self) -> Sequence[Listing]:
        """Get listings past their TTL."""
        result = await self.session.execute(
            select(Listing).where(
                and_(
                    Listing.status.in_(["warm", "cold"]),
                    Listing.cold_check_count >= 5,  # max_checks_before_remove
                )
            )
        )
        return result.scalars().all()

    async def get_all_active(self) -> Sequence[Listing]:
        """Get all non-removed, non-expired listings."""
        result = await self.session.execute(select(Listing).where(Listing.status.not_in(["removed", "expired"])))
        return result.scalars().all()

    async def delete(self, listing: Listing):
        """Delete a listing."""
        await self.session.delete(listing)

    async def count_by_status(self) -> dict[str, int]:
        """Count listings grouped by status."""
        from sqlalchemy import func

        result = await self.session.execute(select(Listing.status, func.count(Listing.id)).group_by(Listing.status))
        return {row[0]: row[1] for row in result.all()}


# ── EvaluationRepository ─────────────────────────────────────────────────────


class EvaluationRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, data: dict) -> EvaluationLog:
        """Create a new evaluation log entry."""
        log = EvaluationLog(**data)
        self.session.add(log)
        return log

    async def get_by_listing_id(self, listing_id: int) -> Sequence[EvaluationLog]:
        """Get all evaluations for a listing, newest first."""
        result = await self.session.execute(
            select(EvaluationLog)
            .where(EvaluationLog.listing_id == listing_id)
            .order_by(EvaluationLog.evaluated_at.desc())
        )
        return result.scalars().all()

    async def get_latest(self, listing_id: int) -> EvaluationLog | None:
        """Get the most recent evaluation for a listing."""
        result = await self.session.execute(
            select(EvaluationLog)
            .where(EvaluationLog.listing_id == listing_id)
            .order_by(EvaluationLog.evaluated_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()


# ── SearchQueryRepository ────────────────────────────────────────────────────


class SearchQueryRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_enabled(self) -> Sequence[SearchQuery]:
        """Get all enabled search queries."""
        result = await self.session.execute(select(SearchQuery).where(SearchQuery.enabled))
        return result.scalars().all()

    async def create_or_update(
        self,
        name: str,
        source: str,
        query_params: dict,
        interval_minutes: int = 60,
        max_pages: int = 5,
        origin: str = "yaml",
    ) -> SearchQuery:
        """Create or update a search query by name+source."""
        result = await self.session.execute(
            select(SearchQuery).where(and_(SearchQuery.name == name, SearchQuery.source == source))
        )
        existing = result.scalar_one_or_none()

        if existing:
            existing.query_params = json.dumps(query_params, ensure_ascii=False)
            existing.interval_minutes = interval_minutes
            existing.max_pages = max_pages
            existing.enabled = True
            existing.updated_at = datetime.now(timezone.utc)
            return existing
        else:
            sq = SearchQuery(
                name=name,
                source=source,
                query_params=json.dumps(query_params, ensure_ascii=False),
                interval_minutes=interval_minutes,
                max_pages=max_pages,
                origin=origin,
            )
            self.session.add(sq)
            return sq

    async def seed_from_yaml(self, yaml_queries: list) -> int:
        """Seed DB from YAML-loaded queries. Returns count of inserted."""
        count = 0
        for yq in yaml_queries:
            params_dict = {
                "city": yq.params.city,
                "type": yq.params.listing_type,
                "rooms": yq.params.rooms,
                "price_from": yq.params.price_from,
                "price_to": yq.params.price_to,
                "area_from": yq.params.area_from,
                "area_to": yq.params.area_to,
                "build_year_from": yq.params.build_year_from,
                "developer": yq.params.developer,
            }
            db_q = await self.get_by_name(yq.name)
            if not db_q:
                await self.create_or_update(
                    name=yq.name,
                    source=yq.source,
                    query_params=params_dict,
                    interval_minutes=yq.interval_minutes,
                    max_pages=yq.max_pages,
                    origin="yaml",
                )
                count += 1
        return count

    async def get_by_name(self, name: str) -> SearchQuery | None:
        result = await self.session.execute(select(SearchQuery).where(SearchQuery.name == name))
        return result.scalar_one_or_none()


# ── MarketStatRepository ─────────────────────────────────────────────────────


class MarketStatRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_for_district(self, city: str, district: str, listing_type: str) -> MarketStat | None:
        """Get latest market stats for a district."""
        result = await self.session.execute(
            select(MarketStat)
            .where(
                and_(
                    MarketStat.city == city,
                    MarketStat.district == district,
                    MarketStat.listing_type == listing_type,
                )
            )
            .order_by(MarketStat.updated_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def upsert(self, data: dict) -> MarketStat:
        """Upsert market stats."""
        existing = await self.get_for_district(data["city"], data["district"], data["listing_type"])
        if existing:
            for key, value in data.items():
                setattr(existing, key, value)
            return existing
        else:
            stat = MarketStat(**data)
            self.session.add(stat)
            return stat
