"""Parser for Cian listing detail pages — extracts full data from inline JSON."""

from __future__ import annotations

import json
import re
from typing import Any

from src.scrapers.base import RawListing

# ── Constants ────────────────────────────────────────────────────────────────

REPAIR_TYPE_MAP: dict[str, str] = {
    "no": "no_repair",
    "cosmetic": "cosmetic",
    "designer": "design",
    "developer": "developer",
    "good": "good",
    "exchange": "exchange",
}


# ── Public API ───────────────────────────────────────────────────────────────


def parse_listing_page(html: str) -> RawListing | None:
    """Extract full listing data from a Cian detail page HTML.

    Strategy: find the ``offerData`` JSON object inside <script>,
    parse it, and map all fields to RawListing.
    """
    offer_data = _extract_offer_data(html)
    if offer_data is None:
        return None

    offer = offer_data.get("offer", {})
    if not offer:
        return None

    return _offer_to_listing(offer)


# ── Internal helpers ─────────────────────────────────────────────────────────


def _extract_offer_data(html: str) -> dict[str, Any] | None:
    """Extract the ``offerData`` JSON object from page HTML.

    The data lives inside a <script> tag as:
        "offerData": { ...large JSON object... }
    We use brace-counting to correctly extract the full object.
    """
    match = re.search(r'"offerData":\{', html)
    if match is None:
        return None

    # match.end() is after the `{` of `"offerData":{` — we need to include it
    start = match.start() + len('"offerData":')
    json_str = _extract_balanced_object(html, start)

    if json_str is None:
        return None

    try:
        return json.loads(json_str)
    except json.JSONDecodeError:
        return None


def _extract_balanced_object(html: str, start: int) -> str | None:
    """Extract a balanced JSON object starting at position ``start``.

    Handles nested objects/arrays and string escaping.
    """
    brace_count = 0
    bracket_count = 0
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
            if brace_count == 0:
                break
        elif ch == "[":
            bracket_count += 1
            chars.append(ch)
        elif ch == "]":
            bracket_count -= 1
            chars.append(ch)
        else:
            chars.append(ch)

        i += 1

    if brace_count == 0:
        return "".join(chars)
    return None


def _offer_to_listing(offer: dict[str, Any]) -> RawListing:
    """Convert Cian ``offer`` dict to RawListing with all available fields."""
    cian_id = int(offer.get("cianId", 0))
    bargain = offer.get("bargainTerms", {})
    price = int(bargain.get("price", 0))

    # Geo / address
    geo = offer.get("geo", {})
    address_parts = _extract_address(geo)
    city = address_parts.get("city")
    district = address_parts.get("district")
    street_address = address_parts.get("street_address")
    address = street_address or None

    # Metro — nearest subway
    metro, metro_distance = _extract_nearest_metro(geo)

    # Building
    building = offer.get("building", {})
    total_floors = building.get("floorsCount")
    if total_floors is not None:
        total_floors = int(total_floors)
    build_year = building.get("buildYear")
    house_type = building.get("materialType") or building.get("houseMaterialType")

    # JK / developer
    jk = geo.get("jk", {})
    developer_name = None
    if jk:
        dev = jk.get("developer", {})
        if dev:
            developer_name = dev.get("name")

    # Photos
    photos = offer.get("photos", [])
    photo_urls: list[str] = []
    for ph in photos:
        url = ph.get("url") or ph.get("miniUrl")
        if url:
            photo_urls.append(url)

    # Repair type
    repair_raw = offer.get("repairType")
    repair_type = REPAIR_TYPE_MAP.get(repair_raw, repair_raw) if repair_raw else None

    # Areas — can be strings or numbers
    area = _to_float(offer.get("totalArea"))
    living_area = _to_float(offer.get("livingArea"))
    kitchen_area = _to_float(offer.get("kitchenArea"))

    # Rooms
    rooms = offer.get("roomsCount")
    if rooms is not None:
        rooms = int(rooms)

    # Floor
    floor = offer.get("floorNumber")
    if floor is not None:
        floor = int(floor)

    # Title & description
    title = offer.get("title")
    description = offer.get("description")

    # Ownership
    is_owner = offer.get("isByHomeowner")

    # Determine listing type
    category = offer.get("category", "")
    listing_type = "new_build" if "new" in category or "newbuilding" in category else "secondary"

    return RawListing(
        cian_id=cian_id,
        url=f"https://www.cian.ru/sale/flat/{cian_id}/",
        price=price,
        listing_type=listing_type,
        rooms=rooms,
        area=area,
        living_area=living_area,
        kitchen_area=kitchen_area,
        floor=floor,
        total_floors=total_floors,
        address=address,
        city=city,
        district=district,
        metro=metro,
        metro_distance=metro_distance,
        title=title,
        description=description,
        photos=photo_urls or None,
        photos_count=len(photo_urls) if photo_urls else None,
        developer=developer_name,
        build_year=build_year,
        house_type=house_type,
        repair_type=repair_type,
        is_owner=is_owner,
    )


# ── Sub-parsers ──────────────────────────────────────────────────────────────


def _extract_address(geo: dict[str, Any]) -> dict[str, str | None]:
    """Extract city, district, street address from geo.address array."""
    result: dict[str, str | None] = {"city": None, "district": None, "street_address": None}

    addresses = geo.get("address", [])
    for addr in addresses:
        addr_type = addr.get("type", "")
        full_name = addr.get("fullName", "")

        if addr_type == "location":
            result["city"] = full_name
        elif addr_type == "okrug" or addr_type == "raion":
            result["district"] = full_name
        elif addr_type == "street":
            # Combine street + house
            result["street_address"] = full_name
        elif addr_type == "house":
            if result["street_address"]:
                result["street_address"] = f"{result['street_address']}, {full_name}"
            else:
                result["street_address"] = full_name

    return result


def _extract_nearest_metro(geo: dict[str, Any]) -> tuple[str | None, int | None]:
    """Extract the nearest subway station name and walking distance."""
    undergrounds = geo.get("undergrounds", [])
    if not undergrounds:
        return None, None

    # Sort by travelTime (walking minutes)
    sorted_metros = sorted(undergrounds, key=lambda m: m.get("travelTime", 999))
    nearest = sorted_metros[0]

    name = nearest.get("name")
    distance = nearest.get("travelTime")  # minutes walking
    if distance is not None:
        distance = int(distance)

    return name, distance


def _to_float(value: Any) -> float | None:
    """Convert a value (str or number) to float, or None."""
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None
