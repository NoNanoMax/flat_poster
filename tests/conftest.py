"""Fixtures for tests — paths to saved HTML files."""

from __future__ import annotations

from pathlib import Path

FIXTURES_DIR = Path(__file__).parent / "fixtures"

SEARCH_PAGE_HTML = FIXTURES_DIR / "search_page.html"
LISTING_PAGE_HTML = FIXTURES_DIR / "listing_page.html"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def read_search_page_html() -> str:
    return _read(SEARCH_PAGE_HTML)


def read_listing_page_html() -> str:
    return _read(LISTING_PAGE_HTML)
