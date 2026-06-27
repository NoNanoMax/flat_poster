"""Search query model and loader for config/search_queries.yaml."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class SearchParams:
    """Параметры одного поискового запроса."""

    city: str
    listing_type: str  # "secondary" | "new_build"
    rooms: list[int] = field(default_factory=list)
    price_from: int | None = None
    price_to: int | None = None
    area_from: float | None = None
    area_to: float | None = None
    build_year_from: int | None = None
    developer: str | None = None


@dataclass
class SearchQuery:
    """Один поисковый запрос."""

    name: str
    enabled: bool = True
    source: str = "cian"
    interval_minutes: int = 60
    max_pages: int = 5
    params: SearchParams = field(default_factory=lambda: SearchParams(city="Москва", listing_type="secondary"))


def _parse_params(raw: dict) -> SearchParams:
    """Convert raw YAML dict to SearchParams."""
    type_map = {"flat": "secondary", "new_build": "new_build", "secondary": "secondary"}
    raw_type = raw.get("type", "secondary")
    return SearchParams(
        city=raw.get("city", "Москва"),
        listing_type=type_map.get(raw_type, raw_type),
        rooms=raw.get("rooms", []),
        price_from=raw.get("price_from"),
        price_to=raw.get("price_to"),
        area_from=raw.get("area_from"),
        area_to=raw.get("area_to"),
        build_year_from=raw.get("build_year_from"),
        developer=raw.get("developer"),
    )


def load_search_queries(path: Path | None = None) -> list[SearchQuery]:
    """Load search queries from YAML file."""
    if path is None:
        # flat_parser/config/search_queries.yaml
        path = Path(__file__).resolve().parents[2] / "config" / "search_queries.yaml"

    if not path.exists():
        return []

    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    queries = []
    for raw in data.get("queries", []):
        queries.append(
            SearchQuery(
                name=raw["name"],
                enabled=raw.get("enabled", True),
                source=raw.get("source", "cian"),
                interval_minutes=raw.get("interval_minutes", 60),
                max_pages=raw.get("max_pages", 5),
                params=_parse_params(raw.get("params", {})),
            )
        )
    return queries
