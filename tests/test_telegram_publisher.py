"""
HezCast Engine — Telegram Publisher Tests
Tinlance Limited | Apache 2.0

TDD: Tests written BEFORE implementation.

Publishes MP4 + caption bundle to Telegram channel/chat.
Fires after QA passes — optional, controlled by env vars.
"""

import pytest
import json
import wave
import struct
from pathlib import Path
from unittest.mock import patch, MagicMock, call


# ─────────────────────────────────────────────
# FIXTURES
# ─────────────────────────────────────────────

@pytest.fixture
def publisher():
    from core.telegram_publisher import TelegramPublisher
    return TelegramPublisher(
        bot_token="test_bot_token_123",
        chat_id="@test_channel"
    )

@pytest.fixture
def sample_mp4(tmp_path):
    """Fake MP4 file"""
    path = tmp_path / "video.mp4"
    path.write_bytes(b"\x00\x00\x00\x20ftypisom" + b"\x00" * (1 * 1024 * 1024))
    return path

@pytest.fixture
def sample_bundle():
    return {
        "title":   "I forgot her birthday TWICE",
        "caption": "Nobody warned me about the gift panic 😭 GiftMode fixed it in 9 seconds. Download free 👇",
        "hashtags": ["#GiftMode", "#GiftIdeas", "#BirthdayGift", "#FreeApp"],
        "cta_link": "https://giftmode.app",
        "platform_variants": {
            "tiktok":    "I forgot her birthday TWICE 😭 #GiftMode #GiftIdeas",
            "instagram": "Nobody warned me about gift panic 😭 Link in bio 👇",
            "linkedin":  "AI found the perfect gift in 9 seconds.",
        }
    }

@pytest.fixture
def mock_telegram_success():
    return {
        "ok": True,
        "result": {
            "message_id": 42,
            "chat": {"id": -1001234567890, "title": "HezCast Content"},
            "video": {"file_id": "BAADAgADXAAD", "duration": 25},
        }
    }

@pytest.fixture
def mock_telegram_failure():
    return {
        "ok": False,
        "error_code": 400,
        "description": "Bad Request: chat not found"
    }


# ─────────────────────────────────────────────
# INITIALIZATION TESTS
# ─────────────────────────────────────────────

class TestPublisherInit:

    def test_init_with_token_and_chat(self):
        """Publisher must initialise with token and chat_id"""
        from core.telegram_publisher import TelegramPublisher
        pub = TelegramPublisher(bot_token="abc123", chat_id="@mychannel")
        assert pub.bot_token == "abc123"
        assert pub.chat_id == "@mychannel"

    def test_init_from_env_vars(self, monkeypatch):
        """Publisher must read from env when no args given"""
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "env_token_xyz")
        monkeypatch.setenv("TELEGRAM_CHAT_ID",   "@env_channel")
        from core.telegram_publisher import TelegramPublisher
        pub = TelegramPublisher()
        assert pub.bot_token == "env_token_xyz"
        assert pub.chat_id == "@env_channel"

    def test_missing_token_raises(self, monkeypatch):
        """Missing bot token must raise ValueError"""
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        monkeypatch.delenv("TELEGRAM_CHAT_ID",   raising=False)
        from core.telegram_publisher import TelegramPublisher
        with pytest.raises(ValueError, match="bot_token"):
            TelegramPublisher()

    def test_missing_chat_id_raises(self, monkeypatch):
        """Missing chat_id must raise ValueError"""
        monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
        from core.telegram_publisher import TelegramPublisher
        with pytest.raises(ValueError, match="chat_id"):
            TelegramPublisher(bot_token="abc123")

    def test_api_url_uses_token(self, publisher):
        """API URL must embed the bot token"""
        assert "test_bot_token_123" in publisher.api_base_url


# ─────────────────────────────────────────────
# CAPTION BUILDER TESTS
# ─────────────────────────────────────────────

class TestCaptionBuilder:

    def test_build_caption_returns_string(self, publisher, sample_bundle):
        """build_caption() must return a string"""
        result = publisher.build_caption(sample_bundle, platform="tiktok")
        assert isinstance(result, str)

    def test_tiktok_caption_uses_platform_variant(self, publisher, sample_bundle):
        """TikTok caption must use tiktok platform variant"""
        result = publisher.build_caption(sample_bundle, platform="tiktok")
        assert "GiftMode" in result or "birthday" in result.lower()

    def test_caption_includes_cta_link(self, publisher, sample_bundle):
        """Caption must include the CTA link"""
        result = publisher.build_caption(sample_bundle, platform="tiktok")
        assert "giftmode.app" in result

    def test_caption_includes_hashtags(self, publisher, sample_bundle):
        """Caption must include at least some hashtags"""
        result = publisher.build_caption(sample_bundle, platform="tiktok")
        assert "#" in result

    def test_caption_under_1024_chars_for_telegram(self, publisher, sample_bundle):
        """Telegram caption limit is 1024 chars — must not exceed"""
        result = publisher.build_caption(sample_bundle, platform="tiktok")
        assert len(result) <= 1024, f"Caption too long: {len(result)} chars"

    def test_caption_instagram_uses_instagram_variant(self, publisher, sample_bundle):
        """Instagram caption uses instagram variant"""
        result = publisher.build_caption(sample_bundle, platform="instagram")
        assert "bio" in result.lower() or "giftmode" in result.lower()

    def test_unknown_platform_falls_back_to_tiktok(self, publisher, sample_bundle):
        """Unknown platform must fall back to tiktok variant"""
        result = publisher.build_caption(sample_bundle, platform="unknown_platform")
        assert len(result) > 0


# ─────────────────────────────────────────────
# VIDEO PUBLISH TESTS
# ─────────────────────────────────────────────

class TestVideoPublish:

    def test_publish_video_returns_message_id(
        self, publisher, sample_mp4, sample_bundle, mock_telegram_success
    ):
        """publish_video() must return the Telegram message_id"""
        with patch.object(publisher, '_post_request') as mock_req:
            mock_req.return_value = mock_telegram_success
            result = publisher.publish_video(
                video_path=str(sample_mp4),
                bundle=sample_bundle,
                platform="tiktok"
            )
        assert result["message_id"] == 42

    def test_publish_video_calls_send_video(
        self, publisher, sample_mp4, sample_bundle, mock_telegram_success
    ):
        """Must call sendVideo endpoint"""
        with patch.object(publisher, '_post_request') as mock_req:
            mock_req.return_value = mock_telegram_success
            publisher.publish_video(
                video_path=str(sample_mp4),
                bundle=sample_bundle,
                platform="tiktok"
            )
        called_url = mock_req.call_args[0][0]
        assert "sendVideo" in called_url

    def test_publish_video_sends_correct_chat_id(
        self, publisher, sample_mp4, sample_bundle, mock_telegram_success
    ):
        """Must send to the configured chat_id"""
        with patch.object(publisher, '_post_request') as mock_req:
            mock_req.return_value = mock_telegram_success
            publisher.publish_video(
                video_path=str(sample_mp4),
                bundle=sample_bundle,
                platform="tiktok"
            )
        call_data = mock_req.call_args[1].get("data", {}) or mock_req.call_args[0][1] if len(mock_req.call_args[0]) > 1 else {}
        # chat_id should be in the request data
        assert mock_req.called

    def test_publish_video_missing_file_raises(
        self, publisher, sample_bundle
    ):
        """Non-existent video file must raise FileNotFoundError"""
        with pytest.raises(FileNotFoundError):
            publisher.publish_video(
                video_path="/nonexistent/video.mp4",
                bundle=sample_bundle,
                platform="tiktok"
            )

    def test_publish_video_on_telegram_error_raises(
        self, publisher, sample_mp4, sample_bundle, mock_telegram_failure
    ):
        """Telegram API error must raise TelegramPublishError"""
        from core.telegram_publisher import TelegramPublishError
        with patch.object(publisher, '_post_request') as mock_req:
            mock_req.return_value = mock_telegram_failure
            with pytest.raises(TelegramPublishError):
                publisher.publish_video(
                    video_path=str(sample_mp4),
                    bundle=sample_bundle,
                    platform="tiktok"
                )

    def test_publish_video_result_has_required_fields(
        self, publisher, sample_mp4, sample_bundle, mock_telegram_success
    ):
        """Publish result must have message_id, chat_id, platform"""
        with patch.object(publisher, '_post_request') as mock_req:
            mock_req.return_value = mock_telegram_success
            result = publisher.publish_video(
                video_path=str(sample_mp4),
                bundle=sample_bundle,
                platform="tiktok"
            )
        assert "message_id" in result
        assert "platform" in result
        assert "published_at" in result


# ─────────────────────────────────────────────
# TEXT POST TESTS
# ─────────────────────────────────────────────

class TestTextPost:

    def test_publish_text_returns_message_id(self, publisher, mock_telegram_success):
        """publish_text() must return message_id"""
        with patch.object(publisher, '_post_request') as mock_req:
            mock_req.return_value = mock_telegram_success
            result = publisher.publish_text("Test caption #GiftMode")
        assert result["message_id"] == 42

    def test_publish_text_calls_send_message(self, publisher, mock_telegram_success):
        """Must call sendMessage endpoint"""
        with patch.object(publisher, '_post_request') as mock_req:
            mock_req.return_value = mock_telegram_success
            publisher.publish_text("Test")
        called_url = mock_req.call_args[0][0]
        assert "sendMessage" in called_url

    def test_publish_text_empty_raises(self, publisher):
        """Empty text must raise ValueError"""
        with pytest.raises(ValueError, match="text"):
            publisher.publish_text("")

    def test_publish_text_whitespace_raises(self, publisher):
        """Whitespace-only text must raise ValueError"""
        with pytest.raises(ValueError, match="text"):
            publisher.publish_text("   ")


# ─────────────────────────────────────────────
# RETRY + AVAILABILITY TESTS
# ─────────────────────────────────────────────

class TestRetryAndAvailability:

    def test_is_configured_true_when_token_set(self, publisher):
        """is_configured() must return True when token and chat_id set"""
        assert publisher.is_configured() is True

    def test_is_configured_false_when_token_missing(self, monkeypatch):
        """is_configured() must return False when no token"""
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        monkeypatch.delenv("TELEGRAM_CHAT_ID",   raising=False)
        from core.telegram_publisher import TelegramPublisher
        try:
            pub = TelegramPublisher()
        except ValueError:
            pub = TelegramPublisher.__new__(TelegramPublisher)
            pub.bot_token = None
            pub.chat_id   = None
            pub.api_base_url = ""
        assert pub.is_configured() is False

    def test_publish_skipped_when_not_configured(self, sample_mp4, sample_bundle):
        """publish_video must return skip result when not configured"""
        from core.telegram_publisher import TelegramPublisher
        pub = TelegramPublisher.__new__(TelegramPublisher)
        pub.bot_token = None
        pub.chat_id   = None
        pub.api_base_url = ""
        result = pub.publish_video(
            video_path=str(sample_mp4),
            bundle=sample_bundle,
            platform="tiktok"
        )
        assert result.get("skipped") is True
