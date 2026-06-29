"""Tests for cold storage strategies."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from src.cold_storage.strategies import (
    CheckAction,
    ColdStrategy,
    RemovalStrategy,
    WarmStrategy,
    determine_action,
    get_strategy_for_verdict,
)
from src.config.settings import ColdStorageSettings


@pytest.fixture
def settings():
    return ColdStorageSettings(
        warm_check_interval_hours=24,
        cold_check_interval_hours=72,
        max_checks_before_remove=5,
        ttl_days=30,
        price_drop_threshold_pct=5.0,
    )


@pytest.fixture
def mock_listing():
    listing = MagicMock()
    listing.cian_id = 123456
    listing.status = "warm"
    listing.last_verdict = "warm"
    listing.price = 10_000_000
    listing.cold_check_count = 2
    listing.created_at = datetime.now(timezone.utc) - timedelta(days=10)
    listing.ttl_days = 30
    return listing


# ── Strategy classes ─────────────────────────────────────────────────────────


class TestWarmStrategy:
    def test_check_interval(self):
        strategy = WarmStrategy()
        assert strategy.check_interval_hours == 24

    def test_next_check_at(self, mock_listing):
        strategy = WarmStrategy()
        now = datetime.now(timezone.utc)
        mock_listing.created_at = now
        next_at = strategy.next_check_at(mock_listing)
        expected = now + timedelta(hours=24)
        # Allow 1-second drift
        assert abs((next_at - expected).total_seconds()) < 1


class TestColdStrategy:
    def test_check_interval(self):
        strategy = ColdStrategy()
        assert strategy.check_interval_hours == 72

    def test_next_check_at(self, mock_listing):
        strategy = ColdStrategy()
        now = datetime.now(timezone.utc)
        next_at = strategy.next_check_at(mock_listing)
        expected = now + timedelta(hours=72)
        assert abs((next_at - expected).total_seconds()) < 1


# ── RemovalStrategy ──────────────────────────────────────────────────────────


class TestRemovalStrategy:
    def test_max_checks_exceeded(self, mock_listing, settings):
        mock_listing.cold_check_count = 5
        removal = RemovalStrategy()
        assert removal.should_remove(mock_listing, settings) is True

    def test_max_checks_not_exceeded(self, mock_listing, settings):
        mock_listing.cold_check_count = 4
        removal = RemovalStrategy()
        assert removal.should_remove(mock_listing, settings) is False

    def test_ttl_expired(self, mock_listing, settings):
        mock_listing.cold_check_count = 0
        mock_listing.created_at = datetime.now(timezone.utc) - timedelta(days=31)
        removal = RemovalStrategy()
        assert removal.should_remove(mock_listing, settings) is True

    def test_ttl_not_expired(self, mock_listing, settings):
        mock_listing.cold_check_count = 0
        mock_listing.created_at = datetime.now(timezone.utc) - timedelta(days=20)
        removal = RemovalStrategy()
        assert removal.should_remove(mock_listing, settings) is False

    def test_ttl_not_expired_at_boundary(self, mock_listing, settings):
        mock_listing.cold_check_count = 0
        # Exactly 30 days ago — should NOT remove (>= means expired)
        mock_listing.created_at = datetime.now(timezone.utc) - timedelta(days=30)
        removal = RemovalStrategy()
        # 30 days ago == exactly at boundary → should_remove (utcnow >= created_at + 30d)
        assert removal.should_remove(mock_listing, settings) is True

    def test_no_removal_needed(self, mock_listing, settings):
        mock_listing.cold_check_count = 0
        mock_listing.created_at = datetime.now(timezone.utc) - timedelta(days=5)
        removal = RemovalStrategy()
        assert removal.should_remove(mock_listing, settings) is False


# ── determine_action ─────────────────────────────────────────────────────────


class TestDetermineAction:
    def test_price_drop_re_evaluate(self, mock_listing, settings):
        """Price dropped 10% → RE_EVALUATE."""
        new_price = 9_000_000  # 10% drop
        action = determine_action(mock_listing, new_price, settings)
        assert action == CheckAction.RE_EVALUATE

    def test_price_drop_at_threshold(self, mock_listing, settings):
        """Price dropped exactly 5% → RE_EVALUATE (>= threshold)."""
        new_price = 9_500_000  # exactly 5% drop
        action = determine_action(mock_listing, new_price, settings)
        assert action == CheckAction.RE_EVALUATE

    def test_price_drop_below_threshold(self, mock_listing, settings):
        """Price dropped 4% → SKIP (below threshold)."""
        new_price = 9_600_000  # 4% drop
        action = determine_action(mock_listing, new_price, settings)
        assert action == CheckAction.SKIP

    def test_price_unchanged(self, mock_listing, settings):
        """Price same → SKIP."""
        action = determine_action(mock_listing, 10_000_000, settings)
        assert action == CheckAction.SKIP

    def test_price_increased(self, mock_listing, settings):
        """Price increased → SKIP."""
        action = determine_action(mock_listing, 11_000_000, settings)
        assert action == CheckAction.SKIP

    def test_new_price_none_delisted(self, mock_listing, settings):
        """new_price is None → REMOVE (delisted)."""
        action = determine_action(mock_listing, None, settings)
        assert action == CheckAction.REMOVE

    def test_max_checks_remove(self, mock_listing, settings):
        """cold_check_count >= max → REMOVE regardless of price."""
        mock_listing.cold_check_count = 5
        action = determine_action(mock_listing, 9_000_000, settings)
        assert action == CheckAction.REMOVE

    def test_ttl_expired_remove(self, mock_listing, settings):
        """TTL expired → REMOVE regardless of price."""
        mock_listing.created_at = datetime.now(timezone.utc) - timedelta(days=31)
        action = determine_action(mock_listing, 9_000_000, settings)
        assert action == CheckAction.REMOVE

    def test_max_checks_takes_priority_over_price_drop(self, mock_listing, settings):
        """Even if price dropped, max_checks still wins."""
        mock_listing.cold_check_count = 5
        action = determine_action(mock_listing, 5_000_000, settings)
        assert action == CheckAction.REMOVE

    def test_ttl_takes_priority_over_price_drop(self, mock_listing, settings):
        """Even if price dropped, TTL expiry still wins."""
        mock_listing.created_at = datetime.now(timezone.utc) - timedelta(days=31)
        action = determine_action(mock_listing, 5_000_000, settings)
        assert action == CheckAction.REMOVE

    def test_price_zero_handling(self, mock_listing, settings):
        """listing.price is 0 → no division by zero."""
        mock_listing.price = 0
        action = determine_action(mock_listing, 500, settings)
        # price == 0 → skip the drop check → SKIP
        assert action == CheckAction.SKIP

    def test_price_negative_handling(self, mock_listing, settings):
        """listing.price is negative → skip the drop check."""
        mock_listing.price = -100
        action = determine_action(mock_listing, 500, settings)
        assert action == CheckAction.SKIP


# ── get_strategy_for_verdict ─────────────────────────────────────────────────


class TestGetStrategyForVerdict:
    def test_warm_verdict(self):
        strategy = get_strategy_for_verdict("warm")
        assert isinstance(strategy, WarmStrategy)
        assert strategy.check_interval_hours == 24

    def test_cold_verdict(self):
        strategy = get_strategy_for_verdict("cold")
        assert isinstance(strategy, ColdStrategy)
        assert strategy.check_interval_hours == 72

    def test_hot_verdict_fallback(self):
        """Hot listings shouldn't be in cold storage, but we handle it."""
        strategy = get_strategy_for_verdict("hot")
        assert isinstance(strategy, WarmStrategy)

    def test_reject_verdict_fallback(self):
        strategy = get_strategy_for_verdict("reject")
        assert isinstance(strategy, WarmStrategy)

    def test_unknown_verdict_fallback(self):
        strategy = get_strategy_for_verdict("foobar")
        assert isinstance(strategy, WarmStrategy)
