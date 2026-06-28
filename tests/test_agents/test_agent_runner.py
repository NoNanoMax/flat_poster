"""Tests for LLMClient (agent_runner)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agents.agent_runner import LLMClient, LLMResponse


def _mock_choice(content: str, reasoning: str = "", finish_reason: str = "stop"):
    """Create a mock chat completion response."""
    mock_resp = MagicMock()
    mock_resp.choices = [
        MagicMock(
            message=MagicMock(content=content, reasoning=reasoning),
            finish_reason=finish_reason,
        )
    ]
    mock_resp.usage = MagicMock(prompt_tokens=100, completion_tokens=200)
    return mock_resp


class TestLLMClientChat:
    """LLMClient.chat() tests with mocked _client."""

    @pytest.fixture
    def client(self):
        """Create LLMClient with a real __init__ but mocked _client."""
        with patch("src.agents.agent_runner.AsyncOpenAI"):
            from src.config.settings import LLMSettings

            client = LLMClient(
                LLMSettings(
                    base_url="http://localhost:8000/v1",
                    model="qwen36",
                    temperature=0.7,
                    max_tokens=2000,
                )
            )
        yield client

    async def test_simple_chat(self, client: LLMClient):
        mock_resp = _mock_choice("Hello")
        client._client = MagicMock()
        client._client.chat = MagicMock()
        client._client.chat.completions = MagicMock()
        client._client.chat.completions.create = AsyncMock(return_value=mock_resp)

        result = await client.chat([{"role": "user", "content": "Hi"}])
        assert isinstance(result, LLMResponse)
        assert result.content == "Hello"
        assert result.finish_reason == "stop"
        assert result.usage["prompt_tokens"] == 100

    async def test_chat_with_reasoning(self, client: LLMClient):
        mock_resp = _mock_choice("Answer", reasoning="Let me think...")
        client._client = MagicMock()
        client._client.chat = MagicMock()
        client._client.chat.completions = MagicMock()
        client._client.chat.completions.create = AsyncMock(return_value=mock_resp)

        result = await client.chat([{"role": "user", "content": "2+2?"}])
        assert result.reasoning == "Let me think..."

    async def test_json_mode(self, client: LLMClient):
        mock_resp = _mock_choice('{"x": 1}')
        client._client = MagicMock()
        client._client.chat = MagicMock()
        client._client.chat.completions = MagicMock()
        client._client.chat.completions.create = AsyncMock(return_value=mock_resp)

        await client.chat([{"role": "user", "content": "test"}], force_json=True)

        call_kwargs = client._client.chat.completions.create.call_args[1]
        assert call_kwargs["response_format"] == {"type": "json_object"}

    async def test_retry_on_truncated_increases_tokens(self, client: LLMClient):
        mock_resp = _mock_choice("OK")
        client._client = MagicMock()
        client._client.chat = MagicMock()
        client._client.chat.completions = MagicMock()
        client._client.chat.completions.create = AsyncMock(side_effect=[ValueError("Response truncated"), mock_resp])

        await client.chat([{"role": "user", "content": "test"}], max_tokens=1000)

        calls = client._client.chat.completions.create.call_args_list
        assert len(calls) == 2
        assert calls[0][1]["max_tokens"] == 1000
        assert calls[1][1]["max_tokens"] == 1500

    async def test_raises_after_exhausted_retries(self, client: LLMClient):
        client._client = MagicMock()
        client._client.chat = MagicMock()
        client._client.chat.completions = MagicMock()
        client._client.chat.completions.create = AsyncMock(side_effect=RuntimeError("server error"))

        with pytest.raises(RuntimeError, match="failed after 3 retries"):
            await client.chat([{"role": "user", "content": "test"}])

    async def test_enable_thinking_false(self, client: LLMClient):
        mock_resp = _mock_choice("OK")
        client._client = MagicMock()
        client._client.chat = MagicMock()
        client._client.chat.completions = MagicMock()
        client._client.chat.completions.create = AsyncMock(return_value=mock_resp)

        await client.chat([{"role": "user", "content": "test"}])

        call_kwargs = client._client.chat.completions.create.call_args[1]
        assert call_kwargs["extra_body"] == {"enable_thinking": False}


class TestLLMClientEvaluateJson:
    """LLMClient.evaluate_json() tests."""

    @pytest.fixture
    def client(self):
        with patch("src.agents.agent_runner.AsyncOpenAI"):
            from src.config.settings import LLMSettings

            return LLMClient(
                LLMSettings(
                    base_url="http://localhost:8000/v1",
                    model="qwen36",
                    temperature=0.7,
                    max_tokens=2000,
                )
            )

    async def test_parses_json(self, client: LLMClient):
        mock_resp = _mock_choice('{"score": 85, "verdict": "hot"}')
        client._client = MagicMock()
        client._client.chat = MagicMock()
        client._client.chat.completions = MagicMock()
        client._client.chat.completions.create = AsyncMock(return_value=mock_resp)

        result = await client.evaluate_json([{"role": "user", "content": "test"}])
        assert result == {"score": 85, "verdict": "hot"}

    async def test_raises_on_invalid_json(self, client: LLMClient):
        mock_resp = _mock_choice("not json at all")
        client._client = MagicMock()
        client._client.chat = MagicMock()
        client._client.chat.completions = MagicMock()
        client._client.chat.completions.create = AsyncMock(return_value=mock_resp)

        with pytest.raises(ValueError, match="invalid JSON"):
            await client.evaluate_json([{"role": "user", "content": "test"}])

    async def test_raises_on_empty_content(self, client: LLMClient):
        mock_resp = _mock_choice("")
        client._client = MagicMock()
        client._client.chat = MagicMock()
        client._client.chat.completions = MagicMock()
        client._client.chat.completions.create = AsyncMock(return_value=mock_resp)

        with pytest.raises(ValueError, match="invalid JSON"):
            await client.evaluate_json([{"role": "user", "content": "test"}])
