"""SQLAlchemy async models for the real estate aggregator."""

from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


# ── Listing ──────────────────────────────────────────────────────────────────


class Listing(Base):
    __tablename__ = "listings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    cian_id = Column(Integer, unique=True, nullable=False, index=True)
    source = Column(String(50), nullable=False, default="cian")
    url = Column(String(500), nullable=False)

    # Основная информация
    title = Column(String(500))
    listing_type = Column(String(20), nullable=False)  # new_build | secondary

    # Цена
    price = Column(Integer, nullable=False)
    price_per_sqm = Column(Float)
    price_history = Column(Text)  # JSON: [{"date": "...", "price": 12000000}]

    # Площадь
    area = Column(Float)
    living_area = Column(Float)
    kitchen_area = Column(Float)

    # Расположение
    rooms = Column(Integer)
    floor = Column(Integer)
    total_floors = Column(Integer)
    address = Column(String(500))
    city = Column(String(200), index=True)
    district = Column(String(200), index=True)
    metro = Column(String(200))
    metro_distance = Column(Integer)

    # Описание
    description = Column(Text)
    photos = Column(Text)  # JSON: ["url1", "url2", ...]

    # Новостройка
    developer = Column(String(200), index=True)
    delivery_date = Column(String(50))
    building_class = Column(String(50))
    finishing = Column(String(100))

    # Вторичка
    build_year = Column(Integer)
    house_type = Column(String(100))
    repair_type = Column(String(100))

    # Статус и метаданные
    status = Column(String(20), nullable=False, default="new", index=True)
    # new, evaluating, hot, warm, cold, published, removed, expired

    last_checked = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # Оценочные поля
    last_score = Column(Float)
    last_verdict = Column(String(10))
    publish_count = Column(Integer, default=0)
    cold_check_count = Column(Integer, default=0)
    ttl_days = Column(Integer, default=30)
    next_check_at = Column(DateTime, nullable=True)

    # Relationships
    evaluations = relationship("EvaluationLog", back_populates="listing", cascade="all, delete-orphan")

    def update_price(self, new_price: int) -> bool:
        """Update price and append to history. Returns True if price changed."""
        if new_price == self.price:
            return False
        history: list[dict] = json.loads(self.price_history or "[]")  # type: ignore[arg-type]
        history.append({"date": datetime.utcnow().isoformat(), "price": self.price})
        self.price = new_price
        self.price_history = json.dumps(history, ensure_ascii=False)
        if self.area and self.area > 0:
            self.price_per_sqm = round(self.price / self.area, 2)
        return True


# ── EvaluationLog ────────────────────────────────────────────────────────────


class EvaluationLog(Base):
    __tablename__ = "evaluation_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    listing_id = Column(Integer, ForeignKey("listings.id"), nullable=False, index=True)

    score = Column(Float)
    verdict = Column(String(10))  # hot, warm, cold, reject

    reasoning = Column(Text)
    pros = Column(Text)  # JSON: ["plus1", "plus2"]
    cons = Column(Text)  # JSON: ["minus1", "minus2"]

    # Детализация
    price_assessment = Column(String(20))  # very_cheap, cheap, fair, expensive, very_expensive
    location_score = Column(Float)
    quality_score = Column(Float)
    investment_score = Column(Float)

    # Для сравнения
    market_price_per_sqm = Column(Float)
    price_vs_market_pct = Column(Float)

    evaluated_at = Column(DateTime, server_default=func.now())

    # Relationship
    listing = relationship("Listing", back_populates="evaluations")

    # ── Helpers ────────────────────────────────────────────────────────────

    @property
    def pros_list(self) -> list[str]:
        """Parse pros JSON to list."""
        if not self.pros:
            return []
        try:
            return json.loads(self.pros)
        except (json.JSONDecodeError, TypeError):
            return []

    @property
    def cons_list(self) -> list[str]:
        """Parse cons JSON to list."""
        if not self.cons:
            return []
        try:
            return json.loads(self.cons)
        except (json.JSONDecodeError, TypeError):
            return []


# ── SearchQuery (DB storage) ────────────────────────────────────────────────


class SearchQuery(Base):
    __tablename__ = "search_queries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(200), nullable=False)
    source = Column(String(50), nullable=False, default="cian")
    enabled = Column(Boolean, default=True)

    # Фильтры
    query_params = Column(Text, nullable=False)  # JSON

    # Расписание
    interval_minutes = Column(Integer, default=60)
    max_pages = Column(Integer, default=5)

    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # Источник: yaml или generated (от market_analyst)
    origin = Column(String(20), default="yaml")  # yaml | generated


# ── MarketStat ───────────────────────────────────────────────────────────────


class MarketStat(Base):
    __tablename__ = "market_stats"

    id = Column(Integer, primary_key=True, autoincrement=True)
    city = Column(String(200), nullable=False, index=True)
    district = Column(String(200), index=True)
    listing_type = Column(String(20))  # new_build | secondary

    avg_price_per_sqm = Column(Float)
    median_price_per_sqm = Column(Float)
    min_price_per_sqm = Column(Float)
    max_price_per_sqm = Column(Float)
    sample_size = Column(Integer)

    updated_at = Column(DateTime, server_default=func.now())


# ── Helpers ──────────────────────────────────────────────────────────────────


def to_dict(model) -> dict:
    """Convert SQLAlchemy model to dict."""
    if model is None:
        return {}
    return {c.name: getattr(model, c.name) for c in model.__table__.columns}
