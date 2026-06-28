"""Scraper base classes and shared data models."""

from __future__ import annotations

import random
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from src.config.queries import SearchQuery
from src.config.settings import ScraperSettings

# ── Region ID map ────────────────────────────────────────────────────────────

REGION_MAP: dict[str, str] = {
    "Москва": "1",
    "Московская область": "650",
}


# ── Raw data model ───────────────────────────────────────────────────────────


@dataclass
class RawListing:
    """Flat listing data extracted from Cian (before DB persistence)."""

    # Identity
    cian_id: int
    url: str

    # Core
    price: int
    listing_type: str  # "new_build" | "secondary"

    # Space
    rooms: int | None = None
    area: float | None = None
    living_area: float | None = None
    kitchen_area: float | None = None

    # Location
    floor: int | None = None
    total_floors: int | None = None
    address: str | None = None
    city: str | None = None
    district: str | None = None
    metro: str | None = None
    metro_distance: int | None = None

    # Text
    title: str | None = None
    description: str | None = None

    # Media
    photos: list[str] | None = None
    photos_count: int | None = None

    # New building fields
    developer: str | None = None
    delivery_date: str | None = None
    building_class: str | None = None
    finishing: str | None = None

    # Secondary fields
    build_year: int | None = None
    house_type: str | None = None
    repair_type: str | None = None

    # Metadata
    is_owner: bool | None = None
    has_good_price: bool | None = None

    # ── Helpers ──────────────────────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict suitable for ListingRepo.upsert()."""
        result: dict[str, Any] = {}
        for fld_name in (
            "cian_id",
            "url",
            "price",
            "listing_type",
            "rooms",
            "area",
            "living_area",
            "kitchen_area",
            "floor",
            "total_floors",
            "address",
            "city",
            "district",
            "metro",
            "metro_distance",
            "title",
            "description",
            "photos",
            "developer",
            "delivery_date",
            "building_class",
            "finishing",
            "build_year",
            "house_type",
            "repair_type",
        ):
            val = getattr(self, fld_name)
            if val is not None:
                if fld_name == "photos" and isinstance(val, list):
                    import json

                    result[fld_name] = json.dumps(val, ensure_ascii=False)
                else:
                    result[fld_name] = val
        return result


# ── Abstract scraper ─────────────────────────────────────────────────────────


class BaseScraper(ABC):
    """Abstract base class for site-specific scrapers."""

    def __init__(self, settings: ScraperSettings):
        self._settings = settings

    # ── Abstract methods ────────────────────────────────────────────────────

    @abstractmethod
    async def fetch_search_page(self, query: SearchQuery, page: int = 1) -> list[RawListing]:
        """Fetch one page of search results and return brief listings."""

    @abstractmethod
    async def fetch_listing_details(self, cian_id: int, brief: RawListing | None = None) -> RawListing | None:
        """Fetch full details for a single listing by Cian ID."""

    # ── Shared helpers ──────────────────────────────────────────────────────

    def _build_search_url(self, query: SearchQuery, page: int = 1) -> str:
        """Build Cian search URL from a SearchQuery."""
        from urllib.parse import urlencode

        params: dict[str, str] = {
            "p": str(page),
            "deal_type": "sale",
            "offer_type": "flat",
            "region": REGION_MAP.get(query.params.city, "1"),
        }

        if query.params.rooms:
            params["room1"] = str(min(query.params.rooms))
            params["room2"] = str(max(query.params.rooms))

        if query.params.price_from:
            params["price_from"] = str(query.params.price_from)
        if query.params.price_to:
            params["price_to"] = str(query.params.price_to)

        return f"https://cian.ru/cat.php?{urlencode(params)}"

    def _build_listing_url(self, cian_id: int) -> str:
        """Build Cian listing detail URL."""
        return f"https://www.cian.ru/sale/flat/{cian_id}/"

    def _delay(self) -> None:
        """Random delay between requests (±20% around configured value)."""
        base = self._settings.delay_between_requests
        jitter = base * 0.2
        time.sleep(base + random.uniform(-jitter, jitter))
