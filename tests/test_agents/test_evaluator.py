"""Tests for EvaluationAgent."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

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


class TestEvaluateBatch:
    """evaluate_batch — concurrent LLM + sequential DB."""

    def _make_listing_mock(self, cian_id: int) -> MagicMock:
        listing = MagicMock(spec=Listing)
        listing.cian_id = cian_id
        listing.id = cian_id
        listing.title = f"Квартира {cian_id}"
        listing.listing_type = "secondary"
        listing.price = 10000000
        listing.price_per_sqm = 200000.0
        listing.rooms = 1
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
        listing.description = "Описание"
        return listing

    def _make_eval_result(self, score: float = 80.0, verdict: str = "hot") -> dict:
        return {
            "score": score,
            "verdict": verdict,
            "reasoning": "test",
            "pros": [],
            "cons": [],
            "price_assessment": "cheap",
            "location_score": 70.0,
            "quality_score": 75.0,
            "investment_score": 85.0,
            "market_price_per_sqm": 200000.0,
            "price_vs_market_pct": -10.0,
        }

    async def test_batch_evaluates_all(self, mock_llm_client):
        """All listings evaluated successfully."""
        mock_llm_client.evaluate_json = AsyncMock(return_value=self._make_eval_result())

        listings = [self._make_listing_mock(i) for i in range(1, 4)]
        agent = EvaluationAgent(mock_llm_client)
        session = MagicMock()
        session.commit = AsyncMock()

        with patch("src.agents.evaluator.ListingRepo") as mock_repo_cls, patch(
            "src.agents.evaluator.EvaluationRepo",
        ) as mock_eval_repo_cls:
            mock_repo = MagicMock()
            mock_repo_cls.return_value = mock_repo
            mock_repo.get_pending_evaluation = AsyncMock(return_value=listings)
            mock_repo.set_status = AsyncMock()

            mock_eval_repo = MagicMock()
            mock_eval_repo_cls.return_value = mock_eval_repo
            mock_eval_repo.create = AsyncMock()

            results = await agent.evaluate_batch(session, limit=10, max_concurrent=2)

        # All 3 evaluated
        assert len(results) == 3
        # LLM called 3 times (concurrently but 3 total)
        assert mock_llm_client.evaluate_json.call_count == 3

    async def test_batch_handles_partial_failure(self, mock_llm_client):
        """One listing fails — others still succeed, failed rolls back to 'new'."""

        call_count = 0

        async def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise RuntimeError("LLM timeout")
            return self._make_eval_result(score=80.0 + call_count)

        mock_llm_client.evaluate_json = AsyncMock(side_effect=side_effect)

        listings = [self._make_listing_mock(i) for i in range(1, 4)]
        agent = EvaluationAgent(mock_llm_client)
        session = MagicMock()
        session.commit = AsyncMock()

        with patch("src.agents.evaluator.ListingRepo") as mock_repo_cls, patch(
            "src.agents.evaluator.EvaluationRepo",
        ) as mock_eval_repo_cls:
            mock_repo = MagicMock()
            mock_repo_cls.return_value = mock_repo
            mock_repo.get_pending_evaluation = AsyncMock(return_value=listings)
            mock_repo.set_status = AsyncMock()

            mock_eval_repo = MagicMock()
            mock_eval_repo_cls.return_value = mock_eval_repo
            mock_eval_repo.create = AsyncMock()

            results = await agent.evaluate_batch(session, limit=10, max_concurrent=3)

        # 2 succeeded, 1 failed
        assert len(results) == 2

        # set_status called: 3x "evaluating" + 1x "new" (rollback) = 4
        assert mock_repo.set_status.call_count >= 4

        # Verify failed one rolled back to "new"
        rollback_calls = [
            c for c in mock_repo.set_status.call_args_list if c[0][1] == "new"
        ]
        assert len(rollback_calls) == 1

    async def test_batch_empty_returns_empty(self, mock_llm_client):
        """No pending listings → empty results."""
        agent = EvaluationAgent(mock_llm_client)
        session = MagicMock()

        with patch("src.agents.evaluator.ListingRepo") as mock_repo_cls:
            mock_repo = MagicMock()
            mock_repo_cls.return_value = mock_repo
            mock_repo.get_pending_evaluation = AsyncMock(return_value=[])

            results = await agent.evaluate_batch(session)

        assert results == []
        assert mock_llm_client.evaluate_json.call_count == 0

    async def test_batch_runs_concurrently(self, mock_llm_client):
        """LLM calls should run in parallel, not sequentially."""
        call_times: list[float] = []
        start_time: float | None = None

        async def side_effect(*args, **kwargs):
            nonlocal start_time
            if start_time is None:
                start_time = asyncio.get_event_loop().time()
            call_times.append(asyncio.get_event_loop().time() - start_time)
            # Simulate 100ms LLM call
            await asyncio.sleep(0.1)
            return self._make_eval_result()

        mock_llm_client.evaluate_json = AsyncMock(side_effect=side_effect)

        listings = [self._make_listing_mock(i) for i in range(1, 6)]  # 5 listings
        agent = EvaluationAgent(mock_llm_client)
        session = MagicMock()
        session.commit = AsyncMock()

        with patch("src.agents.evaluator.ListingRepo") as mock_repo_cls, patch(
            "src.agents.evaluator.EvaluationRepo",
        ) as mock_eval_repo_cls:
            mock_repo = MagicMock()
            mock_repo_cls.return_value = mock_repo
            mock_repo.get_pending_evaluation = AsyncMock(return_value=listings)
            mock_repo.set_status = AsyncMock()

            mock_eval_repo = MagicMock()
            mock_eval_repo_cls.return_value = mock_eval_repo
            mock_eval_repo.create = AsyncMock()

            results = await agent.evaluate_batch(session, limit=10, max_concurrent=3)

        assert len(results) == 5

        # With max_concurrent=3 and 5 items at 100ms each:
        # Sequential: 500ms. Concurrent (3): ~200ms (2 batches).
        # First 3 should start roughly together (within 50ms of each other)
        if len(call_times) >= 3:
            first_three = sorted(call_times[:3])
            assert first_three[-1] - first_three[0] < 0.05, (
                "First 3 calls should start concurrently"
            )

    async def test_batch_respects_max_concurrent(self, mock_llm_client):
        """Semaphore limits parallelism to max_concurrent."""
        max_concurrent_observed = 0
        current_concurrent = 0

        async def side_effect(*args, **kwargs):
            nonlocal current_concurrent, max_concurrent_observed
            current_concurrent += 1
            max_concurrent_observed = max(max_concurrent_observed, current_concurrent)
            await asyncio.sleep(0.05)
            current_concurrent -= 1
            return self._make_eval_result()

        mock_llm_client.evaluate_json = AsyncMock(side_effect=side_effect)

        listings = [self._make_listing_mock(i) for i in range(1, 11)]  # 10 listings
        agent = EvaluationAgent(mock_llm_client)
        session = MagicMock()
        session.commit = AsyncMock()

        with patch("src.agents.evaluator.ListingRepo") as mock_repo_cls, patch(
            "src.agents.evaluator.EvaluationRepo",
        ) as mock_eval_repo_cls:
            mock_repo = MagicMock()
            mock_repo_cls.return_value = mock_repo
            mock_repo.get_pending_evaluation = AsyncMock(return_value=listings)
            mock_repo.set_status = AsyncMock()

            mock_eval_repo = MagicMock()
            mock_eval_repo_cls.return_value = mock_eval_repo
            mock_eval_repo.create = AsyncMock()

            results = await agent.evaluate_batch(session, limit=10, max_concurrent=3)

        assert len(results) == 10
        assert max_concurrent_observed <= 3, (
            f"Max concurrent should be ≤ 3, got {max_concurrent_observed}"
        )
        # With 10 items and concurrency 3, it should actually hit 3 at some point
        assert max_concurrent_observed == 3
