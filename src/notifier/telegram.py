"""Telegram notifier — sends messages to a Telegram channel via aiogram."""

from __future__ import annotations

import asyncio

import httpx
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter, TelegramServerError
from loguru import logger

from src.config.settings import TelegramSettings
from src.notifier.console import ConsoleNotifier, NotifierABC

# ── Markdown escaper ─────────────────────────────────────────────────────────

_MD_CHARS = r"\`*_()~>{}[]#+-=.|!"


def _escape_md(text: str) -> str:
    """Escape Telegram MarkdownV2 special characters."""
    result = []
    for ch in text:
        if ch in _MD_CHARS:
            result.append("\\")
        result.append(ch)
    return "".join(result)


# ── Telegram notifier ────────────────────────────────────────────────────────


class TelegramNotifier(NotifierABC):
    """Sends messages to a Telegram channel via aiogram Bot API.

    Falls back to ConsoleNotifier if token/channel_id are missing.
    """

    def __init__(self, settings: TelegramSettings):
        self._settings = settings
        self._bot: Bot | None = None
        self._fallback: NotifierABC | None = None

        if not settings.token or not settings.channel_id:
            logger.warning("Telegram token or channel_id not set — using ConsoleNotifier fallback")
            self._fallback = ConsoleNotifier()
            return

        self._bot = Bot(token=settings.token)

    async def send(
        self,
        text: str,
        *,
        photo_url: str | None = None,
    ) -> None:
        """Send a message to the Telegram channel.

        If photo_url is provided, sends as a photo with caption.
        """
        if self._fallback is not None:
            await self._fallback.send(text, photo_url=photo_url)
            return

        if self._bot is None:
            return

        # Telegram MarkdownV2 needs escaping of all special chars
        safe_text = _escape_md(text)
        if photo_url:
            safe_caption = safe_text[:1024]  # caption limit
            await self._send_with_retry(
                self._bot.send_photo,
                self._settings.channel_id,
                photo_url,
                caption=safe_caption,
                parse_mode="MarkdownV2",
            )
        else:
            await self._send_with_retry(
                self._bot.send_message,
                self._settings.channel_id,
                safe_text,
                parse_mode="MarkdownV2",
            )

    async def _send_with_retry(
        self,
        func,
        *args,
        retries: int = 3,
        **kwargs,
    ) -> None:
        """Call an aiogram Bot method with retry logic."""
        for attempt in range(1, retries + 1):
            try:
                await func(*args, **kwargs)
                return
            except TelegramRetryAfter as exc:
                wait = exc.retry_after
                logger.warning(
                    "Telegram rate limit (attempt {}/{}), waiting {}s...",
                    attempt,
                    retries,
                    wait,
                )
                await asyncio.sleep(wait)
            except TelegramServerError:
                wait = 2**attempt
                logger.warning(
                    "Telegram server error (attempt {}/{}), retrying in {}s...",
                    attempt,
                    retries,
                    wait,
                )
                await asyncio.sleep(wait)
            except TelegramBadRequest as exc:
                # Bad request — don't retry, just log
                logger.error("Telegram bad request: {}", exc)
                return
            except httpx.HTTPError as exc:
                wait = 2**attempt
                logger.warning(
                    "HTTP error on Telegram send (attempt {}/{}): {}. Retrying in {}s...",
                    attempt,
                    retries,
                    exc,
                    wait,
                )
                await asyncio.sleep(wait)
            except Exception as exc:
                logger.error("Unexpected error sending Telegram message: {}", exc)
                return

        logger.error("Failed to send Telegram message after {} retries", retries)

    async def close(self) -> None:
        """Close the bot session."""
        if self._bot is not None:
            await self._bot.session.close()
