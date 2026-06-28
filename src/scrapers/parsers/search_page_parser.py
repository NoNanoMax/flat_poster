"""Parser for Cian search result pages — extracts brief listings from inline JSON."""

from __future__ import annotations

import json
import re
from typing import Any

from src.scrapers.base import RawListing

# ── Constants ────────────────────────────────────────────────────────────────

OBJECT_TYPE_MAP: dict[str, str] = {
    "flat_new": "new_build",
    "flat_old": "secondary",
}


# ── Public API ───────────────────────────────────────────────────────────────


def parse_search_page(html: str) -> list[RawListing]:
    """Extract brief listings from a Cian search page HTML.

    Strategy: find inline JSON with ``"products":[...]`` inside <script>,
    split into individual objects, parse each into RawListing.
    """
    # 1) Locate the products array
    products_block = _extract_products_block(html)
    if products_block is None:
        return []

    # 2) Parse individual product dicts
    products = _split_and_parse(products_block)

    # 3) Convert to RawListing
    listings: list[RawListing] = []
    for prod in products:
        raw = _product_to_listing(prod)
        if raw is not None:
            listings.append(raw)

    return listings


# ── Internal helpers ─────────────────────────────────────────────────────────


def _extract_products_block(html: str) -> str | None:
    """Return the raw string of the ``products`` array content (without surrounding brackets).

    Uses bracket-counting to handle nested arrays like ``variant:[]``.
    The products array ends when we see ``]`` at brace_count == 0.
    """
    match = re.search(r'"products":\[(?=\s*\{)', html)
    if match is None:
        # Fallback: try without lookahead
        match = re.search(r'"products":\[', html)
    if match is None:
        return None

    start = match.end()
    brace_count = 0
    in_string = False
    escape_next = False
    chars: list[str] = []

    i = start
    while i < len(html):
        ch = html[i]

        if escape_next:
            chars.append(ch)
            escape_next = False
            i += 1
            continue

        if ch == "\\" and in_string:
            chars.append(ch)
            escape_next = True
            i += 1
            continue

        if ch == '"':
            in_string = not in_string
            chars.append(ch)
            i += 1
            continue

        if in_string:
            chars.append(ch)
            i += 1
            continue

        if ch == "{":
            brace_count += 1
            chars.append(ch)
        elif ch == "}":
            brace_count -= 1
            chars.append(ch)
        elif ch == "]" and brace_count == 0:
            # This is the closing bracket of the products array
            break
        else:
            chars.append(ch)

        i += 1

    if brace_count == 0:
        return "".join(chars)
    return None


def _split_and_parse(block: str) -> list[dict[str, Any]]:
    """Parse a concatenated ``{obj},{obj},...`` block into individual JSON objects.

    Uses brace-counting to find top-level object boundaries.
    """
    products: list[dict[str, Any]] = []
    current: list[str] = []
    brace_count = 0
    in_string = False
    escape_next = False

    for ch in block:
        if escape_next:
            current.append(ch)
            escape_next = False
            continue

        if ch == "\\" and in_string:
            current.append(ch)
            escape_next = True
            continue

        if ch == '"':
            in_string = not in_string
            current.append(ch)
            continue

        if in_string:
            current.append(ch)
            continue

        if ch == "{":
            brace_count += 1
            current.append(ch)
        elif ch == "}":
            brace_count -= 1
            current.append(ch)
            if brace_count == 0:
                # Complete object found
                obj_str = "".join(current)
                current = []
                try:
                    obj = json.loads(obj_str)
                    products.append(obj)
                except json.JSONDecodeError:
                    continue
        else:
            # Skip separators (commas, whitespace) between objects
            if brace_count == 0:
                continue
            current.append(ch)

    return products


def _product_to_listing(prod: dict[str, Any]) -> RawListing | None:
    """Convert a single product dict from Cian search JSON to RawListing."""
    cian_id = prod.get("cianId") or prod.get("id")
    if cian_id is None:
        return None

    cian_id = int(cian_id)
    price = int(prod.get("price", 0))
    obj_type = prod.get("objectType", "flat_old")
    listing_type = OBJECT_TYPE_MAP.get(obj_type, "secondary")
    photos_count = prod.get("photosCount")
    is_owner = prod.get("owner")
    extra = prod.get("extra", {}) or {}
    has_good_price = "goodPrice" in extra

    return RawListing(
        cian_id=cian_id,
        url=f"https://www.cian.ru/sale/flat/{cian_id}/",
        price=price,
        listing_type=listing_type,
        photos_count=photos_count,
        is_owner=is_owner,
        has_good_price=has_good_price is not None and has_good_price,
    )
