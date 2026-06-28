"""Tests for Cian listing detail parser."""

from __future__ import annotations

import pytest

from src.scrapers.parsers.listing_parser import parse_listing_page
from tests.conftest import read_listing_page_html


@pytest.fixture(scope="module")
def listing_html():
    return read_listing_page_html()


class TestParseListingPage:
    """parse_listing_page() on real Cian HTML."""

    def test_returns_listing(self, listing_html: str):
        result = parse_listing_page(listing_html)
        assert result is not None

    def test_cian_id(self, listing_html: str):
        result = parse_listing_page(listing_html)
        assert result is not None
        assert result.cian_id > 0

    def test_url(self, listing_html: str):
        result = parse_listing_page(listing_html)
        assert result is not None
        assert result.url.startswith("https://www.cian.ru/sale/flat/")
        assert str(result.cian_id) in result.url

    def test_price(self, listing_html: str):
        result = parse_listing_page(listing_html)
        assert result is not None
        assert result.price > 0

    def test_title(self, listing_html: str):
        result = parse_listing_page(listing_html)
        assert result is not None
        assert result.title is not None
        assert len(result.title) > 0

    def test_rooms(self, listing_html: str):
        result = parse_listing_page(listing_html)
        assert result is not None
        assert result.rooms is not None
        assert result.rooms > 0

    def test_area(self, listing_html: str):
        result = parse_listing_page(listing_html)
        assert result is not None
        assert result.area is not None
        assert result.area > 0

    def test_floor(self, listing_html: str):
        result = parse_listing_page(listing_html)
        assert result is not None
        assert result.floor is not None
        assert result.floor > 0

    def test_total_floors(self, listing_html: str):
        result = parse_listing_page(listing_html)
        assert result is not None
        assert result.total_floors is not None
        assert result.floor is not None
        assert result.total_floors >= result.floor

    def test_city(self, listing_html: str):
        result = parse_listing_page(listing_html)
        assert result is not None
        assert result.city is not None
        assert result.city == "Москва"

    def test_district(self, listing_html: str):
        result = parse_listing_page(listing_html)
        assert result is not None
        assert result.district is not None

    def test_metro(self, listing_html: str):
        result = parse_listing_page(listing_html)
        assert result is not None
        assert result.metro is not None
        assert result.metro_distance is not None
        assert result.metro_distance > 0

    def test_address(self, listing_html: str):
        result = parse_listing_page(listing_html)
        assert result is not None
        # Some listings may have None address (new builds), but this one should have it
        assert result.address is not None

    def test_photos(self, listing_html: str):
        result = parse_listing_page(listing_html)
        assert result is not None
        assert result.photos is not None
        assert len(result.photos) > 0
        for url in result.photos:
            assert url.startswith("https://")

    def test_description(self, listing_html: str):
        result = parse_listing_page(listing_html)
        assert result is not None
        assert result.description is not None
        assert len(result.description) > 10

    def test_build_year(self, listing_html: str):
        result = parse_listing_page(listing_html)
        assert result is not None
        assert result.build_year is not None
        assert result.build_year > 1900

    def test_is_owner(self, listing_html: str):
        result = parse_listing_page(listing_html)
        assert result is not None
        assert result.is_owner is not None

    def test_listing_type(self, listing_html: str):
        result = parse_listing_page(listing_html)
        assert result is not None
        assert result.listing_type in ("new_build", "secondary")

    def test_developer(self, listing_html: str):
        result = parse_listing_page(listing_html)
        assert result is not None
        # This specific listing has a developer
        assert result.developer is not None
        assert len(result.developer) > 0


class TestParseListingPageEdgeCases:
    """Edge cases for parse_listing_page()."""

    def test_empty_html_returns_none(self):
        assert parse_listing_page("") is None

    def test_html_without_offer_data_returns_none(self):
        assert parse_listing_page("<html><body>No offer data</body></html>") is None

    def test_malformed_offer_data_returns_none(self):
        html = '<script>"offerData":{"offer":{INVALID JSON}}</script>'
        assert parse_listing_page(html) is None
