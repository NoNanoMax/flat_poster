"""Formatting engine for listing + evaluation → human-readable text."""

from __future__ import annotations

from typing import Any

from src.db.models import EvaluationLog, Listing

# ── Emoji maps ───────────────────────────────────────────────────────────────

VERDICT_EMOJI: dict[str, str] = {
    "hot": "🔥",
    "warm": "☀️",
    "cold": "❄️",
}

PRICE_EMOJI: dict[str, str] = {
    "very_cheap": "⬇️⬇️",
    "cheap": "⬇️",
    "fair": "✅",
    "expensive": "⬆️",
    "very_expensive": "⬆️⬆️",
}

LISTING_TYPE_DISPLAY: dict[str, str] = {
    "new_build": "Новостройка",
    "secondary": "Вторичка",
}

REPAIR_TYPE_DISPLAY: dict[str, str] = {
    "no_repair": "Без ремонта",
    "cosmetic": "Косметический",
    "design": "Дизайнерский",
    "developer": "От застройщика",
    "good": "Хороший",
    "exchange": "Спец. ремонт",
}

HOUSE_TYPE_DISPLAY: dict[str, str] = {
    "monolith": "Монолит",
    "monolith_brick": "Монолит-кирпич",
    "brick": "Кирпич",
    "panel": "Панельный",
    "block": "Блочный",
    "wood": "Деревянный",
    "stalin": "Сталинка",
}


# ── Helpers ──────────────────────────────────────────────────────────────────


def _fmt_price(price: int | None) -> str:
    if price is None:
        return "—"
    return f"{price:,}".replace(",", " ") + " ₽"


def _fmt_price_short(price: int | None) -> str:
    """Short price: 10 000 000 → 10 млн."""
    if price is None:
        return "—"
    if price >= 1_000_000:
        return f"{price / 1_000_000:.1f} млн ₽".replace(".0 млн", " млн")
    if price >= 1_000:
        return f"{price / 1_000:.0f} тыс ₽"
    return f"{price} ₽"


def _fmt_float(val: float | None, suffix: str = " м²") -> str:
    if val is None:
        return "—"
    return f"{val:.1f}{suffix}"


def _fmt_opt(val: Any, suffix: str = "") -> str:
    if val is None:
        return "—"
    return f"{val}{suffix}"


def _escape_md(text: str) -> str:
    """Escape Telegram Markdown special characters."""
    # Telegram MarkdownV2 special chars: \ ` * _ ( ) ~ ` > | { } [ ] # + - = . !
    result = []
    for ch in text:
        if ch in r"\`*_()~>{}[]#+-=.|!":
            result.append("\\")
        result.append(ch)
    return "".join(result)


# ── Formatter ────────────────────────────────────────────────────────────────


class ListingFormatter:
    """Turns a Listing + EvaluationResult into formatted text."""

    def format_for_telegram(
        self,
        listing: Listing,
        evaluation: EvaluationLog,
    ) -> str:
        """Format listing + evaluation as a Telegram message (Markdown)."""
        verdict = evaluation.verdict or "cold"
        emoji = VERDICT_EMOJI.get(verdict, "📋")
        score = evaluation.score or 0

        lines: list[str] = []

        # Header
        lines.append(f"{emoji} *{_escape_md(verdict.upper())}* | Score: *{score:.0f}/100*")
        lines.append("")

        # Property summary
        rooms = _fmt_opt(listing.rooms)
        area = _fmt_float(listing.area)
        district = listing.district or "—"
        metro_line = self._fmt_metro(listing)
        lines.append(f"📍 *{_escape_md(f'{rooms}-комн. кв., {area}')} — {district}, {metro_line}")

        # Price
        price = _fmt_price(listing.price)
        ppq = _fmt_price(listing.price_per_sqm) if listing.price_per_sqm else "—"
        lines.append(f"💰 *{price}* ({ppq}/м²)")

        # Extra property details
        extra = self._fmt_property_details(listing)
        if extra:
            lines.append(f"🏗 {extra}")

        lines.append("")

        # Scores
        loc_s = evaluation.location_score or 0
        qual_s = evaluation.quality_score or 0
        inv_s = evaluation.investment_score or 0
        lines.append("📊 *Оценка:*")
        lines.append(
            f"  📍 Локация: *{loc_s:.0f}/100*  |  🏠 Качество: *{qual_s:.0f}/100*  |  📈 Инвестиции: *{inv_s:.0f}/100*"
        )

        # Price assessment
        price_assessment = evaluation.price_assessment or "fair"
        price_emoji = PRICE_EMOJI.get(price_assessment, "✅")
        price_vs = evaluation.price_vs_market_pct
        if price_vs is not None:
            if price_vs < 0:
                lines.append(f"  💵 Цена: {price_emoji} ниже рынка на *{abs(price_vs):.0f}%*")
            elif price_vs > 0:
                lines.append(f"  💵 Цена: {price_emoji} выше рынка на *{price_vs:.0f}%*")
            else:
                lines.append(f"  💵 Цена: {price_emoji} соответствует рынку")
        else:
            lines.append(f"  💵 Цена: {price_emoji} {_escape_md(price_assessment)}")

        lines.append("")

        # Pros
        pros = evaluation.pros_list
        if pros:
            lines.append("✅ *Плюсы:*")
            for p in pros:
                lines.append(f"  • {_escape_md(p)}")
            lines.append("")

        # Cons
        cons = evaluation.cons_list
        if cons:
            lines.append("❌ *Минусы:*")
            for c in cons:
                lines.append(f"  • {_escape_md(c)}")
            lines.append("")

        # Reasoning
        reasoning = evaluation.reasoning
        if reasoning:
            lines.append(f"💡 {_escape_md(reasoning)}")
            lines.append("")

        # Link
        lines.append(f"🔗 {_escape_md(listing.url)}")

        return "\n".join(lines)

    def format_for_console(
        self,
        listing: Listing,
        evaluation: EvaluationLog,
    ) -> str:
        """Format listing + evaluation for console output (ANSI colors)."""
        verdict = evaluation.verdict or "cold"
        score = evaluation.score or 0

        # ANSI colors
        colors: dict[str, str] = {
            "hot": "\033[91m",  # red
            "warm": "\033[93m",  # yellow
            "cold": "\033[94m",  # blue
            "reject": "\033[90m",  # dim
        }
        reset = "\033[0m"
        bold = "\033[1m"
        color = colors.get(verdict, reset)

        lines: list[str] = []
        lines.append("")
        lines.append(f"{bold}{color}{'═' * 60}{reset}")
        lines.append(f"{bold}{color} {verdict.upper()} | Score: {score:.0f}/100{reset}")
        lines.append(f"{bold}{color}{'═' * 60}{reset}")

        rooms = _fmt_opt(listing.rooms)
        area = _fmt_float(listing.area)
        lines.append(f"  {rooms}-комн. кв., {area} — {listing.district or '—'}")

        price = _fmt_price(listing.price)
        ppq = _fmt_price(listing.price_per_sqm) if listing.price_per_sqm else "—"
        lines.append(f"  Цена: {price} ({ppq}/м²)")

        extra = self._fmt_property_details(listing)
        if extra:
            lines.append(f"  {extra}")

        metro = self._fmt_metro(listing)
        lines.append(f"  Метро: {metro}")

        lines.append(
            f"  Локация: {evaluation.location_score or 0:.0f}  |  Качество: {evaluation.quality_score or 0:.0f}  |  Инвестиции: {evaluation.investment_score or 0:.0f}"
        )

        reasoning = evaluation.reasoning
        if reasoning:
            lines.append(f"  💡 {reasoning}")

        lines.append(f"  {listing.url}")
        lines.append("")

        return "\n".join(lines)

    # ── Internal helpers ───────────────────────────────────────────────────

    def _fmt_metro(self, listing: Listing) -> str:
        """Format metro line: 'м. Красные ворота (5 мин)'."""
        if not listing.metro:
            return "метро не указано"
        if listing.metro_distance:
            return f"м. {listing.metro} ({listing.metro_distance} мин)"
        return f"м. {listing.metro}"

    def _fmt_property_details(self, listing: Listing) -> str:
        """Format extra property details: building type, year, floor."""
        parts: list[str] = []

        # Building type + year
        house = HOUSE_TYPE_DISPLAY.get(listing.house_type or "", listing.house_type or "")
        if house and house != "—":
            parts.append(house)
        if listing.build_year:
            parts.append(str(listing.build_year))

        # Floor
        if listing.floor and listing.total_floors:
            parts.append(f"{listing.floor}/{listing.total_floors} этаж")
        elif listing.floor:
            parts.append(f"{listing.floor} этаж")

        # Developer (for new builds)
        if listing.developer:
            parts.append(listing.developer)

        # Repair type
        if listing.repair_type:
            repair = REPAIR_TYPE_DISPLAY.get(listing.repair_type, listing.repair_type)
            parts.append(repair)

        return ", ".join(parts) if parts else ""
