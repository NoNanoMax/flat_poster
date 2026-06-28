"""LLM client — thin wrapper over AsyncOpenAI for vLLM with retry logic."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any

from loguru import logger
from openai import AsyncOpenAI

from src.config.settings import LLMSettings


@dataclass
class LLMResponse:
    """Structured response from the LLM."""

    content: str
    reasoning: str  # model's internal thought process
    finish_reason: str
    usage: dict[str, int]  # prompt_tokens, completion_tokens


class LLMClient:
    """Async client for vLLM (OpenAI-compatible API).

    Features:
    - Retry with exponential backoff
    - JSON mode support
    - Built-in reasoning logging
    """

    def __init__(self, settings: LLMSettings):
        self._settings = settings
        self._client = AsyncOpenAI(
            base_url=settings.base_url,
            api_key="token",  # vLLM doesn't require a real key
        )

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        force_json: bool = False,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        """Send a chat request to the LLM and return the response.

        Args:
            messages: OpenAI-style messages list.
            force_json: If True, request JSON output.
            max_tokens: Override default max_tokens.

        Returns:
            LLMResponse with content, reasoning, finish_reason, usage.

        Raises:
            RuntimeError: If all retries exhausted.
        """
        effective_max = max_tokens or self._settings.max_tokens
        retries = 3
        last_error: Exception | None = None

        for attempt in range(1, retries + 1):
            try:
                return await self._do_chat(messages, force_json, effective_max)
            except ValueError as exc:
                # Truncated response — retry with more tokens
                if "truncated" in str(exc):
                    effective_max = int(effective_max * 1.5)
                    logger.warning(
                        "Response truncated, increasing max_tokens to {}. Retrying...",
                        effective_max,
                    )
                    continue
                last_error = exc
                wait = 2 ** (attempt - 1)
                logger.warning(
                    "LLM request failed (attempt {}/{}): {}. Retrying in {}s...",
                    attempt,
                    retries,
                    exc,
                    wait,
                )
                await asyncio.sleep(wait)
            except Exception as exc:
                last_error = exc
                wait = 2 ** (attempt - 1)
                logger.warning(
                    "LLM request failed (attempt {}/{}): {}. Retrying in {}s...",
                    attempt,
                    retries,
                    exc,
                    wait,
                )
                await asyncio.sleep(wait)

        raise RuntimeError(f"LLM request failed after {retries} retries: {last_error}")

    async def _do_chat(
        self,
        messages: list[dict[str, str]],
        force_json: bool,
        max_tokens: int,
    ) -> LLMResponse:
        """Single chat attempt."""
        kwargs: dict[str, Any] = {
            "model": self._settings.model,
            "messages": messages,
            "temperature": self._settings.temperature,
            "max_tokens": max_tokens,
            "timeout": 120.0,  # generous timeout for large responses
            "extra_body": {"enable_thinking": False},
        }

        if force_json:
            kwargs["response_format"] = {"type": "json_object"}

        resp = await self._client.chat.completions.create(**kwargs)

        choice = resp.choices[0]
        msg = choice.message

        content = msg.content or ""
        reasoning = msg.reasoning or ""
        finish_reason = choice.finish_reason or ""
        usage = {
            "prompt_tokens": resp.usage.prompt_tokens if resp.usage else 0,
            "completion_tokens": resp.usage.completion_tokens if resp.usage else 0,
        }

        logger.debug(
            "LLM response: finish={}, tokens={}/{}",
            finish_reason,
            usage["prompt_tokens"],
            usage["completion_tokens"],
        )

        # If truncated, retry with more tokens
        if finish_reason == "length":
            raise ValueError(f"Response truncated (max_tokens={max_tokens}), need more tokens")

        return LLMResponse(
            content=content,
            reasoning=reasoning,
            finish_reason=finish_reason,
            usage=usage,
        )

    async def evaluate_json(
        self,
        messages: list[dict[str, str]],
        *,
        max_tokens: int | None = None,
    ) -> dict:
        """Send a request expecting JSON output.

        Convenience wrapper that parses the JSON response.

        Returns:
            Parsed dict from the LLM response.

        Raises:
            ValueError: If the response is not valid JSON.
        """
        resp = await self.chat(messages, force_json=True, max_tokens=max_tokens)

        try:
            return json.loads(resp.content)
        except json.JSONDecodeError as exc:
            logger.error(
                "Invalid JSON from LLM (reasoning preview: {}): {}",
                resp.reasoning[:200],
                resp.content[:500],
            )
            raise ValueError(f"LLM returned invalid JSON: {exc}") from exc
