"""Tests for CianScraper (non-HTTP parts)."""

from __future__ import annotations

import pytest

from src.config.queries import SearchParams, SearchQuery
from src.config.settings import ScraperSettings
from src.scrapers.base import RawListing
from src.scrapers.cian import CianScraper


@pytest.fixture
def scraper_settings():
    return ScraperSettings(
        delay_between_requests=0.1,
        delay_between_pages=0.2,
        max_pages_per_query=3,
        timeout=10,
        user_agents=["TestAgent/1.0"],
    )


@pytest.fixture
def scraper(scraper_settings: ScraperSettings) -> CianScraper:
    return CianScraper(scraper_settings)


class TestCianScraperBuildUrls:
    """Test URL generation methods."""

    def test_build_search_url_basic(self, scraper: CianScraper):
        query = SearchQuery(
            name="test",
            params=SearchParams(
                city="Москва", listing_type="secondary", rooms=[1], price_from=4000000, price_to=12000000
            ),
        )
        url = scraper._build_search_url(query, page=1)
        assert url.startswith("https://cian.ru/cat.php?")
        assert "region=1" in url
        assert "room1=1" in url
        assert "room2=1" in url
        assert "price_from=4000000" in url
        assert "price_to=12000000" in url
        assert "p=1" in url

    def test_build_search_url_page_2(self, scraper: CianScraper):
        query = SearchQuery(
            name="test",
            params=SearchParams(city="Москва", listing_type="secondary", rooms=[1]),
        )
        url = scraper._build_search_url(query, page=2)
        assert "p=2" in url

    def test_build_search_url_moscow_oblast(self, scraper: CianScraper):
        query = SearchQuery(
            name="test",
            params=SearchParams(city="Московская область", listing_type="secondary", rooms=[2, 3]),
        )
        url = scraper._build_search_url(query, page=1)
        assert "region=650" in url
        assert "room1=2" in url
        assert "room2=3" in url

    def test_build_search_url_unknown_region(self, scraper: CianScraper):
        query = SearchQuery(
            name="test",
            params=SearchParams(city="Санкт-Петербург", listing_type="secondary"),
        )
        url = scraper._build_search_url(query, page=1)
        # Falls back to "1" (Москва)
        assert "region=1" in url

    def test_build_listing_url(self, scraper: CianScraper):
        url = scraper._build_listing_url(123456789)
        assert url == "https://www.cian.ru/sale/flat/123456789/"

    def test_build_search_url_new_build(self, scraper: CianScraper):
        query = SearchQuery(
            name="test",
            params=SearchParams(city="Москва", listing_type="new_build", rooms=[1, 2]),
        )
        url = scraper._build_search_url(query, page=1)
        assert "offer_type=flat" in url
        assert "deal_type=sale" in url


class TestRawListingModel:
    """RawListing dataclass tests."""

    def test_minimal_creation(self):
        bl = RawListing(cian_id=1, url="https://test.ru", price=100, listing_type="secondary")
        assert bl.cian_id == 1
        assert bl.url == "https://test.ru"
        assert bl.price == 100
        assert bl.listing_type == "secondary"
        assert bl.rooms is None
        assert bl.area is None

    def test_full_creation(self):
        bl = RawListing(
            cian_id=42,
            url="https://www.cian.ru/sale/flat/42/",
            price=5000000,
            listing_type="new_build",
            rooms=2,
            area=50.0,
            living_area=35.0,
            kitchen_area=10.0,
            floor=5,
            total_floors=10,
            address="ул. Тестовая, 1",
            city="Москва",
            district="Центральный",
            metro="Тестовая",
            metro_distance=5,
            title="Тестовая квартира",
            description="Описание",
            photos=["https://photo1.jpg"],
            photos_count=1,
            developer="Застройщик",
            build_year=2020,
            house_type="monolith",
            repair_type="design",
            is_owner=False,
            has_good_price=True,
        )
        assert bl.cian_id == 42
        assert bl.rooms == 2
        assert bl.area == 50.0
        assert bl.metro == "Тестовая"
        assert bl.has_good_price is True

    def test_to_dict_with_photos_json(self):
        import json

        bl = RawListing(
            cian_id=1,
            url="https://test.ru",
            price=100,
            listing_type="secondary",
            photos=["https://a.jpg", "https://b.jpg"],
            rooms=2,
            area=50.0,
        )
        d = bl.to_dict()
        assert d["cian_id"] == 1
        assert d["rooms"] == 2
        assert d["area"] == 50.0
        assert "photos" in d
        parsed = json.loads(d["photos"])
        assert parsed == ["https://a.jpg", "https://b.jpg"]

    def test_to_dict_excludes_none(self):
        bl = RawListing(cian_id=1, url="https://test.ru", price=100, listing_type="secondary")
        d = bl.to_dict()
        assert "rooms" not in d
        assert "area" not in d
        assert "address" not in d
        assert "metro" not in d

    def test_to_dict_includes_non_none(self):
        bl = RawListing(
            cian_id=1,
            url="https://test.ru",
            price=100,
            listing_type="secondary",
            rooms=0,
            area=0.0,
        )
        d = bl.to_dict()
        # 0 and 0.0 are not None, so they should be included
        assert d["rooms"] == 0
        assert d["area"] == 0.0
