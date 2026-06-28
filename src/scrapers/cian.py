"""Cian.ru scraper — fetches search results and listing details via cloudscraper."""

from __future__ import annotations

import asyncio
import random

import cloudscraper
from loguru import logger

from src.config.queries import SearchQuery
from src.config.settings import ScraperSettings
from src.scrapers.base import BaseScraper, RawListing
from src.scrapers.parsers.listing_parser import parse_listing_page
from src.scrapers.parsers.search_page_parser import parse_search_page


class CianScraper(BaseScraper):
    """Scraper for cian.ru using cloudscraper to bypass anti-bot protection."""

    def __init__(self, settings: ScraperSettings):
        super().__init__(settings)
        self._scraper: cloudscraper.CloudScraper | None = None

    def _get_scraper(self) -> cloudscraper.CloudScraper:
        """Lazy-init cloudscraper instance with browser fingerprinting."""
        if self._scraper is None:
            self._scraper = cloudscraper.create_scraper(
                browser={"browser": "chrome", "platform": "windows", "desktop": True},
                delay=self._settings.delay_between_requests,
            )
        return self._scraper

    def _rotate_user_agent(self) -> None:
        """Rotate User-Agent header."""
        scraper = self._get_scraper()
        scraper.headers["User-Agent"] = random.choice(self._settings.user_agents)
        scraper.headers["Accept-Language"] = "ru-RU"

    # ── Search page ──────────────────────────────────────────────────────────

    async def fetch_search_page(self, query: SearchQuery, page: int = 1) -> list[RawListing]:
        """Fetch one page of search results for a query.

        Returns a list of brief RawListing objects (cian_id, price, type, URL).
        """
        url = self._build_search_url(query, page)
        logger.info("Fetching search page: {} (page {})", query.name, page)

        html = await asyncio.to_thread(self._fetch_html, url)
        if html is None:
            logger.warning("Failed to fetch search page: {}", url)
            return []

        listings = parse_search_page(html)
        logger.info("Parsed {} listings from page {} of {}", len(listings), page, query.name)
        return listings

    # ── Listing detail ───────────────────────────────────────────────────────

    async def fetch_listing_details(self, cian_id: int, brief: RawListing | None = None) -> RawListing | None:
        """Fetch full details for a single listing by Cian ID.

        Returns a fully populated RawListing or None on failure.
        """
        url = self._build_listing_url(cian_id)
        logger.debug("Fetching listing details: {}", cian_id)

        html = await asyncio.to_thread(self._fetch_html, url)
        if html is None:
            logger.warning("Failed to fetch listing details: {}", cian_id)
            return None

        listing = parse_listing_page(html)
        if listing is None:
            logger.warning("Failed to parse listing details: {}", cian_id)
            return None

        # Preserve brief info if available (e.g. has_good_price from search page)
        if brief:
            if listing.has_good_price is None and brief.has_good_price is not None:
                listing.has_good_price = brief.has_good_price
            if listing.is_owner is None and brief.is_owner is not None:
                listing.is_owner = brief.is_owner

        return listing

    # ── HTTP helpers ─────────────────────────────────────────────────────────

    def _fetch_html(self, url: str) -> str | None:
        """Synchronous HTTP GET via cloudscraper with retry logic.

        Returns HTML string or None on failure.
        """
        scraper = self._get_scraper()
        self._rotate_user_agent()

        max_retries = 3
        for attempt in range(1, max_retries + 1):
            try:
                resp = scraper.get(url, timeout=self._settings.timeout)
                if resp.status_code == 200:
                    return resp.text
                elif resp.status_code == 429:
                    wait = 5 * attempt
                    logger.warning("Rate limited (429), waiting {}s before retry", wait)
                    import time

                    time.sleep(wait)
                    continue
                elif resp.status_code >= 500:
                    wait = 3 * attempt
                    logger.warning("Server error ({}), waiting {}s before retry", resp.status_code, wait)
                    import time

                    time.sleep(wait)
                    continue
                else:
                    logger.warning("Unexpected status {} for {}", resp.status_code, url)
                    return None
            except cloudscraper.exceptions.CloudflareSolverFailure:
                logger.warning("Cloudflare CAPTCHA failed on attempt {}", attempt)
                import time

                time.sleep(5 * attempt)
                # Recreate scraper to get new fingerprint
                self._scraper = None
                continue
            except Exception as exc:
                logger.warning("Request error on attempt {}: {}", attempt, exc)
                import time

                time.sleep(3 * attempt)
                continue

        logger.error("All {} retries exhausted for {}", max_retries, url)
        return None
