"""Tests for Cian search page parser."""

from __future__ import annotations

import pytest

from src.scrapers.base import RawListing
from src.scrapers.parsers.search_page_parser import parse_search_page
from tests.conftest import read_search_page_html


@pytest.fixture(scope="module")
def search_html():
    return read_search_page_html()


class TestParseSearchPage:
    """parse_search_page() on real Cian HTML."""

    def test_returns_non_empty_list(self, search_html: str):
        listings = parse_search_page(search_html)
        assert len(listings) >= 20, f"Expected at least 20 listings, got {len(listings)}"

    def test_all_listings_have_cian_id(self, search_html: str):
        listings = parse_search_page(search_html)
        for bl in listings:
            assert bl.cian_id > 0, f"cian_id should be positive, got {bl.cian_id}"

    def test_all_listings_have_price(self, search_html: str):
        listings = parse_search_page(search_html)
        for bl in listings:
            assert bl.price > 0, f"price should be positive, got {bl.price}"

    def test_all_listings_have_url(self, search_html: str):
        listings = parse_search_page(search_html)
        for bl in listings:
            assert bl.url.startswith("https://www.cian.ru/sale/flat/")
            assert str(bl.cian_id) in bl.url

    def test_listing_type_mapped(self, search_html: str):
        listings = parse_search_page(search_html)
        types = {bl.listing_type for bl in listings}
        assert types.issubset({"new_build", "secondary"})

    def test_photos_count_populated(self, search_html: str):
        listings = parse_search_page(search_html)
        # At least some listings should have photos_count
        with_photos = [bl for bl in listings if bl.photos_count is not None]
        assert len(with_photos) > 0, "Expected some listings to have photos_count"

    def test_is_owner_field(self, search_html: str):
        listings = parse_search_page(search_html)
        # All should have is_owner set (True/False)
        for bl in listings:
            assert bl.is_owner is not None, "is_owner should not be None"

    def test_has_good_price_field(self, search_html: str):
        listings = parse_search_page(search_html)
        for bl in listings:
            assert bl.has_good_price is not None, "has_good_price should not be None"

    def test_no_duplicate_cian_ids(self, search_html: str):
        listings = parse_search_page(search_html)
        ids = [bl.cian_id for bl in listings]
        assert len(ids) == len(set(ids)), "Duplicate cian_ids found"


class TestParseSearchPageEdgeCases:
    """Edge cases for parse_search_page()."""

    def test_empty_html_returns_empty_list(self):
        assert parse_search_page("") == []

    def test_html_without_products_returns_empty_list(self):
        assert parse_search_page("<html><body>No products here</body></html>") == []

    def test_html_with_empty_products_array(self):
        html = '<script>"products":[]</script>'
        assert parse_search_page(html) == []


class TestRawListing:
    """RawListing model tests."""

    def test_to_dict_includes_required_fields(self):
        bl = RawListing(cian_id=123, url="https://test.ru", price=1000000, listing_type="secondary")
        d = bl.to_dict()
        assert d["cian_id"] == 123
        assert d["url"] == "https://test.ru"
        assert d["price"] == 1000000
        assert d["listing_type"] == "secondary"

    def test_to_dict_omits_none_fields(self):
        bl = RawListing(cian_id=123, url="https://test.ru", price=1000000, listing_type="secondary")
        d = bl.to_dict()
        assert "rooms" not in d
        assert "area" not in d

    def test_to_dict_serializes_photos_as_json(self):
        import json

        bl = RawListing(
            cian_id=123,
            url="https://test.ru",
            price=1000000,
            listing_type="secondary",
            photos=["https://photo1.jpg", "https://photo2.jpg"],
        )
        d = bl.to_dict()
        assert "photos" in d
        parsed = json.loads(d["photos"])
        assert parsed == ["https://photo1.jpg", "https://photo2.jpg"]
