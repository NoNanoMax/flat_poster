"""Tests for ConsoleNotifier and TelegramNotifier."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from src.config.settings import TelegramSettings
from src.notifier.console import ConsoleNotifier, NotifierABC
from src.notifier.telegram import TelegramNotifier


class TestConsoleNotifier:
    """ConsoleNotifier tests."""

    async def test_send_prints_to_stdout(self, capsys):
        notifier = ConsoleNotifier()
        await notifier.send("Hello world")
        out = capsys.readouterr()
        assert "Hello world" in out.out

    async def test_send_with_photo_url(self, capsys):
        notifier = ConsoleNotifier()
        await notifier.send("Test", photo_url="https://photo.jpg")
        out = capsys.readouterr()
        assert "Test" in out.out

    async def test_send_batch(self, capsys):
        notifier = ConsoleNotifier()
        await notifier.send_batch(["Msg 1", "Msg 2"])
        out = capsys.readouterr()
        assert "Msg 1" in out.out
        assert "Msg 2" in out.out

    async def test_send_batch_with_photo_urls(self, capsys):
        notifier = ConsoleNotifier()
        await notifier.send_batch(
            ["Msg 1", "Msg 2"],
            photo_urls=["https://a.jpg", None],
        )
        out = capsys.readouterr()
        assert "Msg 1" in out.out
        assert "Msg 2" in out.out


class TestTelegramNotifier:
    """TelegramNotifier tests with mocked Bot."""

    @pytest.fixture
    def tg_settings(self):
        return TelegramSettings(token="123:ABC", channel_id="@test_channel", test_mode=False)

    @pytest.fixture
    def notifier(self, tg_settings):
        with patch("src.notifier.telegram.Bot") as mock_bot_cls:
            mock_bot = AsyncMock()
            mock_bot_cls.return_value = mock_bot
            return TelegramNotifier(tg_settings)

    async def test_send_message(self, notifier):
        notifier._bot = AsyncMock()
        await notifier.send("Test message")
        notifier._bot.send_message.assert_called_once()
        call_args = notifier._bot.send_message.call_args
        assert call_args[0][0] == "@test_channel"

    async def test_send_photo(self, notifier):
        notifier._bot = AsyncMock()
        await notifier.send("Test", photo_url="https://photo.jpg")
        notifier._bot.send_photo.assert_called_once()
        call_args = notifier._bot.send_photo.call_args
        assert call_args[0][0] == "@test_channel"
        assert call_args[0][1] == "https://photo.jpg"

    async def test_fallback_when_no_token(self):
        settings = TelegramSettings(token="", channel_id="@test", test_mode=False)
        notifier = TelegramNotifier(settings)
        # Should use ConsoleNotifier fallback
        assert notifier._fallback is not None

    async def test_fallback_when_no_channel(self):
        settings = TelegramSettings(token="123:ABC", channel_id="", test_mode=False)
        notifier = TelegramNotifier(settings)
        assert notifier._fallback is not None


class TestNotifierABC:
    """NotifierABC interface tests."""

    def test_is_abstract(self):
        with pytest.raises(TypeError):
            NotifierABC()  # type: ignore[misc]

    def test_subclass_implementation(self):
        # ConsoleNotifier should be instantiable
        notifier = ConsoleNotifier()
        assert isinstance(notifier, NotifierABC)
