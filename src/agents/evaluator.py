"""Evaluation agent — scores listings via LLM and persists results."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import yaml
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from src.agents.agent_runner import LLMClient
from src.db.models import Listing
from src.db.repository import EvaluationRepo, ListingRepo

# ── Result model ─────────────────────────────────────────────────────────────


@dataclass
class EvaluationResult:
    """Structured result from the LLM evaluation."""

    score: float
    verdict: str  # hot, warm, cold, reject
    reasoning: str
    pros: list[str]
    cons: list[str]
    price_assessment: str  # very_cheap, cheap, fair, expensive, very_expensive
    location_score: float
    quality_score: float
    investment_score: float
    market_price_per_sqm: float | None
    price_vs_market_pct: float | None


# ── Prompt loader ────────────────────────────────────────────────────────────

_PROMPT_DIR = Path(__file__).parent / "prompt_templates"


def _load_evaluation_prompt() -> dict[str, str]:
    """Load evaluation prompt from YAML."""
    path = _PROMPT_DIR / "evaluation.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Evaluation prompt not found: {path}")
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


# ── Display helpers ──────────────────────────────────────────────────────────


def _fmt_price(value: int | None) -> str:
    if value is None:
        return "N/A"
    return f"{value:,}"


def _fmt_float(value: float | None, suffix: str = " м²") -> str:
    if value is None:
        return "N/A"
    return f"{value:.1f}{suffix}"


def _fmt_optional(value: Any, suffix: str = "") -> str:
    if value is None:
        return "N/A"
    return f"{value}{suffix}"


# ── Agent ────────────────────────────────────────────────────────────────────


class EvaluationAgent:
    """LLM-powered listing evaluator.

    Workflow:
    1. Build prompt from listing data
    2. Send to LLM with JSON mode
    3. Parse result → EvaluationResult
    4. Persist to DB (EvaluationLog + update Listing status)
    """

    def __init__(self, llm_client: LLMClient):
        self._llm = llm_client
        self._prompt = _load_evaluation_prompt()

    # ── Public API ─────────────────────────────────────────────────────────

    async def evaluate(self, listing: Listing) -> EvaluationResult:
        """Evaluate a single listing via LLM.

        Args:
            listing: The listing to evaluate.

        Returns:
            Parsed EvaluationResult.
        """
        messages = self._build_messages(listing)
        raw_dict = await self._llm.evaluate_json(messages, max_tokens=4000)
        return self._parse_response(raw_dict)

    async def evaluate_and_save(
        self,
        session: AsyncSession,
        listing: Listing,
    ) -> EvaluationResult:
        """Evaluate a listing and persist the result.

        Updates listing status and creates an EvaluationLog entry.

        Args:
            session: Active DB session.
            listing: The listing to evaluate.

        Returns:
            The EvaluationResult.
        """
        result = await self.evaluate(listing)

        # Update listing
        listing.last_score = result.score
        listing.last_verdict = result.verdict
        listing.status = result.verdict

        # Set next_check_at based on verdict
        if result.verdict == "warm":
            listing.next_check_at = datetime.utcnow() + timedelta(hours=24)
        elif result.verdict == "cold":
            listing.next_check_at = datetime.utcnow() + timedelta(hours=72)
        else:
            listing.next_check_at = None

        # Save evaluation log
        eval_repo = EvaluationRepo(session)
        await eval_repo.create(
            {
                "listing_id": listing.id,
                "score": result.score,
                "verdict": result.verdict,
                "reasoning": result.reasoning,
                "pros": json.dumps(result.pros, ensure_ascii=False),
                "cons": json.dumps(result.cons, ensure_ascii=False),
                "price_assessment": result.price_assessment,
                "location_score": result.location_score,
                "quality_score": result.quality_score,
                "investment_score": result.investment_score,
                "market_price_per_sqm": result.market_price_per_sqm,
                "price_vs_market_pct": result.price_vs_market_pct,
            }
        )

        logger.info(
            "Evaluated cian_id={}: score={:.0f}, verdict={}",
            listing.cian_id,
            result.score,
            result.verdict,
        )
        return result

    async def evaluate_batch(
        self,
        session: AsyncSession,
        limit: int = 10,
    ) -> list[EvaluationResult]:
        """Evaluate all pending listings up to limit.

        Args:
            session: Active DB session.
            limit: Max listings to evaluate.

        Returns:
            List of EvaluationResults.
        """
        repo = ListingRepo(session)
        listings = await repo.get_pending_evaluation(limit=limit)

        results: list[EvaluationResult] = []
        for listing in listings:
            try:
                await repo.set_status(listing.cian_id, "evaluating")  # type: ignore[arg-type]
                result = await self.evaluate_and_save(session, listing)
                results.append(result)
            except Exception as exc:
                logger.error("Failed to evaluate cian_id={}: {}", listing.cian_id, exc)
                await repo.set_status(listing.cian_id, "new")  # type: ignore[arg-type]
        return results

    # ── Internal helpers ───────────────────────────────────────────────────

    def _build_messages(self, listing: Listing) -> list[dict[str, str]]:
        """Build prompt messages from listing data."""
        user_text = self._prompt[
            "user_template"
        ].format(
            title=listing.title or "N/A",
            listing_type_display=self._listing_type_display(listing.listing_type),  # type: ignore[arg-type]
            price_display=_fmt_price(listing.price),  # type: ignore[arg-type]
            price_per_sqm_display=_fmt_price(round(listing.price_per_sqm, 0)) if listing.price_per_sqm else "N/A",
            rooms=_fmt_optional(listing.rooms),  # type: ignore[arg-type]
            area_display=_fmt_float(listing.area),  # type: ignore[arg-type]
            living_area_display=_fmt_float(listing.living_area),  # type: ignore[arg-type]
            kitchen_area_display=_fmt_float(listing.kitchen_area),  # type: ignore[arg-type]
            floor_display=f"{listing.floor}/{listing.total_floors}"
            if listing.floor and listing.total_floors
            else _fmt_optional(listing.floor),
            address_display=listing.address or "N/A",
            district_display=listing.district or "N/A",
            metro_display=f"{listing.metro} ({listing.metro_distance} мин пешком)" if listing.metro else "Не указано",  # noqa: RUF001
            build_year_display=_fmt_optional(listing.build_year),  # type: ignore[arg-type]
            house_type_display=listing.house_type or "N/A",
            repair_type_display=listing.repair_type or "N/A",
            developer_display=listing.developer or "N/A",
            description_preview=(listing.description or "")[:300],
        )

        return [
            {"role": "system", "content": self._prompt["system"]},
            {"role": "user", "content": user_text},
        ]

    def _listing_type_display(self, listing_type: str) -> str:
        return "Новостройка" if listing_type == "new_build" else "Вторичка"

    def _parse_response(self, data: dict) -> EvaluationResult:
        """Parse LLM JSON response into EvaluationResult with validation."""
        return EvaluationResult(
            score=float(data.get("score", 0)),
            verdict=str(data.get("verdict", "reject")).lower(),
            reasoning=str(data.get("reasoning", "")),
            pros=list(data.get("pros", [])),
            cons=list(data.get("cons", [])),
            price_assessment=str(data.get("price_assessment", "fair")).lower(),
            location_score=float(data.get("location_score", 0)),
            quality_score=float(data.get("quality_score", 0)),
            investment_score=float(data.get("investment_score", 0)),
            market_price_per_sqm=float(data["market_price_per_sqm"])
            if data.get("market_price_per_sqm") is not None
            else None,
            price_vs_market_pct=float(data["price_vs_market_pct"])
            if data.get("price_vs_market_pct") is not None
            else None,
        )
