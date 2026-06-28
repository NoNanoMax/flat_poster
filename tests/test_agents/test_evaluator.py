"""Tests for EvaluationAgent."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.agents.evaluator import EvaluationAgent, EvaluationResult
from src.db.models import Listing


@pytest.fixture
def mock_llm_client():
    return AsyncMock()


@pytest.fixture
def sample_listing():
    listing = MagicMock(spec=Listing)
    listing.cian_id = 123456
    listing.title = "2-комн. кв., 50 м²"
    listing.listing_type = "secondary"
    listing.price = 10000000
    listing.price_per_sqm = 200000
    listing.rooms = 2
    listing.area = 50.0
    listing.living_area = 35.0
    listing.kitchen_area = 10.0
    listing.floor = 5
    listing.total_floors = 10
    listing.address = "ул. Тестовая, 1"
    listing.city = "Москва"
    listing.district = "Центральный"
    listing.metro = "Тестовая"
    listing.metro_distance = 5
    listing.build_year = 2015
    listing.house_type = "monolith"
    listing.repair_type = "design"
    listing.developer = None
    listing.status = "new"
    listing.last_score = None
    listing.last_verdict = None
    listing.description = "Хорошая квартира с ремонтом."  # noqa: RUF001
    return listing


class TestEvaluationResult:
    """EvaluationResult dataclass tests."""

    def test_creation(self):
        result = EvaluationResult(
            score=85.0,
            verdict="hot",
            reasoning="Good deal",
            pros=["Price"],
            cons=["Location"],
            price_assessment="cheap",
            location_score=70.0,
            quality_score=80.0,
            investment_score=90.0,
            market_price_per_sqm=200000.0,
            price_vs_market_pct=-10.0,
        )
        assert result.score == 85.0
        assert result.verdict == "hot"
        assert len(result.pros) == 1


class TestEvaluationAgent:
    """EvaluationAgent tests with mocked LLM."""

    async def test_evaluate_returns_result(self, mock_llm_client, sample_listing):
        mock_llm_client.evaluate_json = AsyncMock(
            return_value={
                "score": 85.0,
                "verdict": "hot",
                "reasoning": "Good price",
                "pros": ["Цена"],
                "cons": ["Этаж"],
                "price_assessment": "cheap",
                "location_score": 70.0,
                "quality_score": 80.0,
                "investment_score": 90.0,
                "market_price_per_sqm": 200000.0,
                "price_vs_market_pct": -10.0,
            }
        )

        agent = EvaluationAgent(mock_llm_client)
        result = await agent.evaluate(sample_listing)

        assert isinstance(result, EvaluationResult)
        assert result.score == 85.0
        assert result.verdict == "hot"
        assert result.reasoning == "Good price"
        assert len(result.pros) == 1

    async def test_evaluate_calls_llm_with_messages(self, mock_llm_client, sample_listing):
        mock_llm_client.evaluate_json = AsyncMock(
            return_value={
                "score": 50.0,
                "verdict": "cold",
                "reasoning": "test",
                "pros": [],
                "cons": [],
                "price_assessment": "fair",
                "location_score": 50.0,
                "quality_score": 50.0,
                "investment_score": 50.0,
                "market_price_per_sqm": None,
                "price_vs_market_pct": None,
            }
        )

        agent = EvaluationAgent(mock_llm_client)
        await agent.evaluate(sample_listing)

        # Check that evaluate_json was called
        mock_llm_client.evaluate_json.assert_called_once()
        messages = mock_llm_client.evaluate_json.call_args.args[0]
        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"

    def test_parse_response_with_minimal_data(self, mock_llm_client):
        agent = EvaluationAgent(mock_llm_client)

        data = {
            "score": 0,
            "verdict": "reject",
            "reasoning": "",
            "pros": [],
            "cons": [],
            "price_assessment": "fair",
            "location_score": 0,
            "quality_score": 0,
            "investment_score": 0,
        }

        result = agent._parse_response(data)
        assert result.score == 0.0
        assert result.verdict == "reject"
        assert result.market_price_per_sqm is None
        assert result.price_vs_market_pct is None

    def test_parse_response_with_nulls(self, mock_llm_client):
        agent = EvaluationAgent(mock_llm_client)

        data = {
            "score": 50.0,
            "verdict": "cold",
            "reasoning": "test",
            "pros": [],
            "cons": [],
            "price_assessment": "fair",
            "location_score": 50.0,
            "quality_score": 50.0,
            "investment_score": 50.0,
            "market_price_per_sqm": None,
            "price_vs_market_pct": None,
        }

        result = agent._parse_response(data)
        assert result.market_price_per_sqm is None
        assert result.price_vs_market_pct is None

    def test_listing_type_display_new_build(self, mock_llm_client):
        agent = EvaluationAgent(mock_llm_client)
        assert agent._listing_type_display("new_build") == "Новостройка"

    def test_listing_type_display_secondary(self, mock_llm_client):
        agent = EvaluationAgent(mock_llm_client)
        assert agent._listing_type_display("secondary") == "Вторичка"
