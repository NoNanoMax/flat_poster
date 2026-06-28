"""Console notifier — prints to stdout with ANSI colors (test_mode)."""

from __future__ import annotations

import sys
from abc import ABC, abstractmethod

from loguru import logger

# ── ANSI color helpers ───────────────────────────────────────────────────────

_RESET = "\033[0m"
_BOLD = "\033[1m"


# ── Abstract notifier interface ─────────────────────────────────────────────


class NotifierABC(ABC):
    """Abstract interface for notification backends."""

    @abstractmethod
    async def send(
        self,
        text: str,
        *,
        photo_url: str | None = None,
    ) -> None:
        """Send a single notification."""

    async def send_batch(
        self,
        texts: list[str],
        *,
        photo_urls: list[str | None] | None = None,
    ) -> None:
        """Send multiple notifications sequentially."""
        urls = photo_urls or [None] * len(texts)
        for text, url in zip(texts, urls, strict=True):
            await self.send(text, photo_url=url)


# ── Console notifier ─────────────────────────────────────────────────────────


class ConsoleNotifier(NotifierABC):
    """Prints to console (stdout) and logs via loguru.

    Used in test_mode instead of real Telegram.
    """

    async def send(
        self,
        text: str,
        *,
        photo_url: str | None = None,
    ) -> None:
        """Print formatted text to console."""
        # Print to stdout — text already contains ANSI colors from formatter
        print(text, file=sys.stdout, flush=True)

        # Also log to file
        if photo_url:
            logger.info("Notification (photo={}):\n{}", photo_url, text)
        else:
            logger.info("Notification:\n{}", text)
