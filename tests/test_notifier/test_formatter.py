"""Tests for notifier formatter."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.db.models import EvaluationLog, Listing
from src.notifier.formatter import ListingFormatter


@pytest.fixture
def formatter():
    return ListingFormatter()


@pytest.fixture
def mock_listing():
    listing = MagicMock(spec=Listing)
    listing.cian_id = 123456
    listing.url = "https://www.cian.ru/sale/flat/123456/"
    listing.title = "2-комн. кв., 50 м²"
    listing.listing_type = "secondary"
    listing.price = 10000000
    listing.price_per_sqm = 200000.0
    listing.rooms = 2
    listing.area = 50.0
    listing.living_area = 35.0
    listing.kitchen_area = 10.0
    listing.floor = 5
    listing.total_floors = 10
    listing.address = "ул. Тестовая, 1"
    listing.city = "Москва"
    listing.district = "Басманный"
    listing.metro = "Красные ворота"
    listing.metro_distance = 5
    listing.build_year = 2015
    listing.house_type = "monolith"
    listing.repair_type = "design"
    listing.developer = None
    listing.description = "Хорошая квартира"
    return listing


@pytest.fixture
def mock_evaluation():
    e = MagicMock(spec=EvaluationLog)
    e.score = 85.0
    e.verdict = "hot"
    e.reasoning = "Отличная сделка в центре."
    e.pros_list = ["Центр города", "Современный ремонт"]
    e.cons_list = ["Маленькая кухня"]
    e.price_assessment = "cheap"
    e.location_score = 90.0
    e.quality_score = 75.0
    e.investment_score = 85.0
    e.market_price_per_sqm = 230000.0
    e.price_vs_market_pct = -13.0
    return e


class TestFormatterTelegram:
    """ListingFormatter.format_for_telegram() tests."""

    def test_hot_verdict_has_fire_emoji(self, formatter, mock_listing, mock_evaluation):
        text = formatter.format_for_telegram(mock_listing, mock_evaluation)
        assert "🔥" in text
        assert "HOT" in text

    def test_contains_score(self, formatter, mock_listing, mock_evaluation):
        text = formatter.format_for_telegram(mock_listing, mock_evaluation)
        assert "85/100" in text

    def test_contains_price(self, formatter, mock_listing, mock_evaluation):
        text = formatter.format_for_telegram(mock_listing, mock_evaluation)
        assert "10 000 000 ₽" in text

    def test_contains_metro(self, formatter, mock_listing, mock_evaluation):
        text = formatter.format_for_telegram(mock_listing, mock_evaluation)
        assert "Красные ворота" in text
        assert "5 мин" in text

    def test_contains_pros_and_cons(self, formatter, mock_listing, mock_evaluation):
        text = formatter.format_for_telegram(mock_listing, mock_evaluation)
        assert "✅" in text
        assert "❌" in text
        assert "Центр города" in text
        assert "Маленькая кухня" in text

    def test_contains_reasoning(self, formatter, mock_listing, mock_evaluation):
        text = formatter.format_for_telegram(mock_listing, mock_evaluation)
        assert "💡" in text
        assert "Отличная сделка" in text

    def test_contains_link(self, formatter, mock_listing, mock_evaluation):
        text = formatter.format_for_telegram(mock_listing, mock_evaluation)
        assert "🔗" in text
        # URL dots are escaped for MarkdownV2, so check for cian or the link prefix
        assert "cian" in text or "cian\\." in text

    def test_warm_verdict(self, formatter, mock_listing, mock_evaluation):
        mock_evaluation.verdict = "warm"
        mock_evaluation.score = 65.0
        text = formatter.format_for_telegram(mock_listing, mock_evaluation)
        assert "☀️" in text
        assert "WARM" in text

    def test_cold_verdict(self, formatter, mock_listing, mock_evaluation):
        mock_evaluation.verdict = "cold"
        mock_evaluation.score = 45.0
        text = formatter.format_for_telegram(mock_listing, mock_evaluation)
        assert "❄️" in text
        assert "COLD" in text

    def test_escapes_markdown_in_reasoning(self, formatter, mock_listing, mock_evaluation):
        # Reasoning goes through _escape_md
        mock_evaluation.reasoning = "Тест [скобки] и *звёзды*"
        text = formatter.format_for_telegram(mock_listing, mock_evaluation)
        # Reasoning should have escaped brackets and stars
        assert "\\[" in text or "\\]" in text

    def test_handles_none_fields(self, formatter, mock_listing, mock_evaluation):
        mock_listing.metro = None
        mock_listing.repair_type = None
        mock_listing.house_type = None
        mock_listing.build_year = None
        mock_listing.developer = None
        text = formatter.format_for_telegram(mock_listing, mock_evaluation)
        # Should not crash
        assert len(text) > 0

    def test_price_vs_market_positive(self, formatter, mock_listing, mock_evaluation):
        mock_evaluation.price_vs_market_pct = 15.0
        text = formatter.format_for_telegram(mock_listing, mock_evaluation)
        assert "выше рынка" in text

    def test_price_vs_market_zero(self, formatter, mock_listing, mock_evaluation):
        mock_evaluation.price_vs_market_pct = 0.0
        text = formatter.format_for_telegram(mock_listing, mock_evaluation)
        assert "соответствует рынку" in text


class TestFormatterConsole:
    """ListingFormatter.format_for_console() tests."""

    def test_console_has_ansi_colors(self, formatter, mock_listing, mock_evaluation):
        text = formatter.format_for_console(mock_listing, mock_evaluation)
        # Red for hot
        assert "\033[91m" in text

    def test_console_has_score(self, formatter, mock_listing, mock_evaluation):
        text = formatter.format_for_console(mock_listing, mock_evaluation)
        assert "85/100" in text

    def test_console_has_url(self, formatter, mock_listing, mock_evaluation):
        text = formatter.format_for_console(mock_listing, mock_evaluation)
        assert "cian.ru" in text

    def test_console_hot_color(self, formatter, mock_listing, mock_evaluation):
        mock_evaluation.verdict = "hot"
        text = formatter.format_for_console(mock_listing, mock_evaluation)
        assert "\033[91m" in text  # red

    def test_console_warm_color(self, formatter, mock_listing, mock_evaluation):
        mock_evaluation.verdict = "warm"
        text = formatter.format_for_console(mock_listing, mock_evaluation)
        assert "\033[93m" in text  # yellow

    def test_console_cold_color(self, formatter, mock_listing, mock_evaluation):
        mock_evaluation.verdict = "cold"
        text = formatter.format_for_console(mock_listing, mock_evaluation)
        assert "\033[94m" in text  # blue


class TestHelperFunctions:
    """Helper function tests."""

    def test_fmt_price(self):
        from src.notifier.formatter import _fmt_price

        assert _fmt_price(10000000) == "10 000 000 ₽"
        assert _fmt_price(500000) == "500 000 ₽"
        assert _fmt_price(None) == "—"

    def test_fmt_float(self):
        from src.notifier.formatter import _fmt_float

        assert _fmt_float(50.0) == "50.0 м²"
        assert _fmt_float(None) == "—"

    def test_fmt_opt(self):
        from src.notifier.formatter import _fmt_opt

        assert _fmt_opt(5) == "5"
        assert _fmt_opt(None) == "—"
        assert _fmt_opt("test", "s") == "tests"
