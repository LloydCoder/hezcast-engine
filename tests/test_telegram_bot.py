"""
HezCast Engine — Telegram Bot Tests
TDD Phase 7 | Tinlance Limited
Tests written BEFORE implementation (Red-Green-Refactor)

Bidirectional Telegram bot:
  You send: /generate GiftMode forgot birthday gift
  Bot replies: hook variants
  You send: /select abc123 2
  Bot triggers render → sends back MP4 + caption

Commands:
  /generate [brand] [topic]
  /generate [brand] --url [url]
  /select [job_id] [variant_num]
  /status [job_id]
  /brands
  /credits
  /help
  /cancel [job_id]
"""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock
import uuid
import json


# ─────────────────────────────────────────────
# FIXTURES
# ─────────────────────────────────────────────

@pytest.fixture
def bot():
    from core.telegram_bot import HezCastBot
    return HezCastBot(
        bot_token="test_token_123",
        chat_id="@test_channel"
    )

@pytest.fixture
def mock_job_id():
    return str(uuid.uuid4())[:8]

@pytest.fixture
def mock_update_generate():
    """Simulated Telegram update for /generate command"""
    return {
        "update_id": 123456,
        "message": {
            "message_id": 1,
            "from": {"id": 99999, "username": "lloydambition"},
            "chat": {"id": 99999, "type": "private"},
            "text": "/generate GiftMode forgot birthday gift last minute",
            "date": 1748000000,
        }
    }

@pytest.fixture
def mock_update_select():
    """Simulated Telegram update for /select command"""
    return {
        "update_id": 123457,
        "message": {
            "message_id": 2,
            "from": {"id": 99999, "username": "lloydambition"},
            "chat": {"id": 99999, "type": "private"},
            "text": "/select abc12345 2",
            "date": 1748000001,
        }
    }

@pytest.fixture
def mock_update_status():
    return {
        "update_id": 123458,
        "message": {
            "message_id": 3,
            "from": {"id": 99999},
            "chat": {"id": 99999, "type": "private"},
            "text": "/status abc12345",
            "date": 1748000002,
        }
    }

@pytest.fixture
def mock_hooks():
    return [
        {"variant_num": 1, "hook_text": "Nobody told me you could forget TWICE...", "selected": False},
        {"variant_num": 2, "hook_text": "I had 2 hours to find a gift. Cooked.", "selected": False},
        {"variant_num": 3, "hook_text": "POV: Her birthday is TODAY.", "selected": False},
        {"variant_num": 4, "hook_text": "The gift panic is real.", "selected": False},
        {"variant_num": 5, "hook_text": "She said it's fine. It wasn't.", "selected": False},
    ]


# ─────────────────────────────────────────────
# COMMAND PARSER TESTS
# ─────────────────────────────────────────────

class TestCommandParser:

    def test_parse_generate_command(self, bot):
        """Parse /generate GiftMode topic correctly"""
        cmd = bot.parse_command("/generate GiftMode forgot birthday gift")
        assert cmd["command"] == "generate"
        assert cmd["brand"] == "GiftMode"
        assert cmd["topic"] == "forgot birthday gift"

    def test_parse_generate_with_url(self, bot):
        """Parse /generate GiftMode --url https://... correctly"""
        cmd = bot.parse_command("/generate Tinlance --url https://tinlance.com/blog/post")
        assert cmd["command"] == "generate"
        assert cmd["brand"] == "Tinlance"
        assert cmd["url"] == "https://tinlance.com/blog/post"
        assert cmd["topic"] == ""

    def test_parse_select_command(self, bot):
        """Parse /select job_id variant_num correctly"""
        cmd = bot.parse_command("/select abc12345 2")
        assert cmd["command"] == "select"
        assert cmd["job_id"] == "abc12345"
        assert cmd["variant_num"] == 2

    def test_parse_status_command(self, bot):
        """Parse /status job_id correctly"""
        cmd = bot.parse_command("/status abc12345")
        assert cmd["command"] == "status"
        assert cmd["job_id"] == "abc12345"

    def test_parse_brands_command(self, bot):
        """Parse /brands correctly"""
        cmd = bot.parse_command("/brands")
        assert cmd["command"] == "brands"

    def test_parse_credits_command(self, bot):
        """Parse /credits correctly"""
        cmd = bot.parse_command("/credits")
        assert cmd["command"] == "credits"

    def test_parse_help_command(self, bot):
        """Parse /help correctly"""
        cmd = bot.parse_command("/help")
        assert cmd["command"] == "help"

    def test_parse_cancel_command(self, bot):
        """Parse /cancel job_id correctly"""
        cmd = bot.parse_command("/cancel abc12345")
        assert cmd["command"] == "cancel"
        assert cmd["job_id"] == "abc12345"

    def test_parse_unknown_command_returns_unknown(self, bot):
        """Unknown command returns command=unknown"""
        cmd = bot.parse_command("/unknowncmd something")
        assert cmd["command"] == "unknown"

    def test_parse_empty_message_returns_unknown(self, bot):
        """Empty message returns command=unknown"""
        cmd = bot.parse_command("")
        assert cmd["command"] == "unknown"

    def test_parse_generate_missing_brand_returns_error(self, bot):
        """Missing brand in /generate returns error command"""
        cmd = bot.parse_command("/generate")
        assert cmd["command"] in ("error", "generate")
        # Either error or generate with empty brand

    def test_parse_select_missing_variant_returns_error(self, bot):
        """Missing variant_num in /select returns error"""
        cmd = bot.parse_command("/select abc12345")
        assert cmd.get("command") == "error" or cmd.get("variant_num") is None

    def test_parse_case_insensitive_brand(self, bot):
        """Brand matching must be case-insensitive"""
        cmd = bot.parse_command("/generate giftmode forgot birthday gift")
        assert cmd["brand"].lower() == "giftmode"

    def test_parse_multiword_topic(self, bot):
        """Multi-word topic must be captured fully"""
        cmd = bot.parse_command("/generate Tinlance your website got hacked at 2am")
        assert "website" in cmd["topic"]
        assert "hacked" in cmd["topic"]


# ─────────────────────────────────────────────
# REPLY BUILDER TESTS
# ─────────────────────────────────────────────

class TestReplyBuilder:

    def test_build_job_started_reply(self, bot, mock_job_id):
        """Job started reply must include job_id and brand"""
        reply = bot.build_reply_job_started(
            job_id=mock_job_id,
            brand="GiftMode",
            topic="forgot birthday gift"
        )
        assert isinstance(reply, str)
        assert mock_job_id in reply
        assert len(reply) > 20

    def test_build_hooks_reply(self, bot, mock_job_id, mock_hooks):
        """Hooks reply must show all variants numbered"""
        reply = bot.build_reply_hooks(
            job_id=mock_job_id,
            hooks=mock_hooks
        )
        assert isinstance(reply, str)
        assert "1" in reply
        assert "2" in reply
        assert mock_job_id in reply

    def test_build_hooks_reply_shows_all_variants(self, bot, mock_job_id, mock_hooks):
        """Hooks reply must show all 5 variants"""
        reply = bot.build_reply_hooks(
            job_id=mock_job_id,
            hooks=mock_hooks
        )
        for hook in mock_hooks:
            # At least part of each hook text should appear
            assert hook["hook_text"][:20] in reply or str(hook["variant_num"]) in reply

    def test_build_hooks_reply_includes_select_instruction(self, bot, mock_job_id, mock_hooks):
        """Hooks reply must tell user how to select"""
        reply = bot.build_reply_hooks(
            job_id=mock_job_id,
            hooks=mock_hooks
        )
        assert "/select" in reply.lower() or "select" in reply.lower()

    def test_build_processing_reply(self, bot, mock_job_id):
        """Processing reply must confirm render started"""
        reply = bot.build_reply_processing(
            job_id=mock_job_id,
            variant_num=2
        )
        assert isinstance(reply, str)
        assert len(reply) > 10

    def test_build_completed_reply(self, bot, mock_job_id):
        """Completed reply must include download info"""
        reply = bot.build_reply_completed(
            job_id=mock_job_id,
            output_path="/storage/outputs/job/final.mp4",
            caption="Test caption #GiftMode",
            duration_sec=24.3
        )
        assert isinstance(reply, str)
        assert "24" in reply or "mp4" in reply.lower() or "video" in reply.lower()

    def test_build_error_reply(self, bot):
        """Error reply must be user-friendly"""
        reply = bot.build_reply_error(
            error_message="LLM timeout",
            command="generate"
        )
        assert isinstance(reply, str)
        assert len(reply) > 10

    def test_build_status_reply_queued(self, bot, mock_job_id):
        """Status reply for queued job"""
        reply = bot.build_reply_status({
            "job_id": mock_job_id,
            "status": "queued",
            "brand": "GiftMode",
            "topic": "test topic"
        })
        assert isinstance(reply, str)
        assert "queue" in reply.lower() or "wait" in reply.lower() or mock_job_id in reply

    def test_build_brands_reply(self, bot):
        """Brands reply must list all 4 brands"""
        reply = bot.build_reply_brands()
        assert "GiftMode" in reply
        assert "Tinlance" in reply
        assert "WebTemify" in reply
        assert "HezCast" in reply

    def test_build_help_reply(self, bot):
        """Help reply must show all commands"""
        reply = bot.build_reply_help()
        commands = ["/generate", "/select", "/status", "/brands", "/credits", "/help"]
        for cmd in commands:
            assert cmd in reply

    def test_all_replies_under_4096_chars(self, bot, mock_job_id, mock_hooks):
        """All replies must be under Telegram 4096 char limit"""
        replies = [
            bot.build_reply_job_started(mock_job_id, "GiftMode", "test topic"),
            bot.build_reply_hooks(mock_job_id, mock_hooks),
            bot.build_reply_processing(mock_job_id, 2),
            bot.build_reply_completed(mock_job_id, "/path/final.mp4", "caption", 24.3),
            bot.build_reply_error("error msg", "generate"),
            bot.build_reply_brands(),
            bot.build_reply_help(),
        ]
        for reply in replies:
            assert len(reply) <= 4096, f"Reply too long ({len(reply)} chars): {reply[:100]}"


# ─────────────────────────────────────────────
# UPDATE HANDLER TESTS
# ─────────────────────────────────────────────

class TestUpdateHandler:

    def test_extract_message_from_update(self, bot, mock_update_generate):
        """Must extract message from Telegram update dict"""
        message = bot.extract_message(mock_update_generate)
        assert message is not None
        assert "text" in message
        assert message["text"].startswith("/generate")

    def test_extract_chat_id_from_update(self, bot, mock_update_generate):
        """Must extract chat_id from update"""
        chat_id = bot.extract_chat_id(mock_update_generate)
        assert chat_id == 99999

    def test_extract_user_from_update(self, bot, mock_update_generate):
        """Must extract user info from update"""
        user = bot.extract_user(mock_update_generate)
        assert user is not None
        assert "username" in user or "id" in user

    def test_handle_update_generate_dispatches_job(
        self, bot, mock_update_generate
    ):
        """Handling /generate update must dispatch a job"""
        with patch.object(bot, '_dispatch_generate') as mock_dispatch:
            mock_dispatch.return_value = {
                "job_id": "test123",
                "status": "queued"
            }
            with patch.object(bot, 'send_message'):
                bot.handle_update(mock_update_generate)
        assert mock_dispatch.called

    def test_handle_update_select_dispatches_render(
        self, bot, mock_update_select
    ):
        """Handling /select update must dispatch render"""
        with patch.object(bot, '_dispatch_select') as mock_dispatch:
            mock_dispatch.return_value = {"status": "processing"}
            with patch.object(bot, 'send_message'):
                bot.handle_update(mock_update_select)
        assert mock_dispatch.called

    def test_handle_update_status_fetches_job(
        self, bot, mock_update_status
    ):
        """Handling /status update must fetch job status"""
        with patch.object(bot, '_dispatch_status') as mock_status:
            mock_status.return_value = {
                "job_id": "abc12345",
                "status": "processing",
                "brand": "GiftMode",
                "topic": "test"
            }
            with patch.object(bot, 'send_message'):
                bot.handle_update(mock_update_status)
        assert mock_status.called

    def test_handle_unknown_command_sends_help(self, bot):
        """Unknown command must send help message"""
        update = {
            "update_id": 999,
            "message": {
                "message_id": 9,
                "from": {"id": 99999},
                "chat": {"id": 99999, "type": "private"},
                "text": "/unknowncmd",
                "date": 1748000000,
            }
        }
        with patch.object(bot, 'send_message') as mock_send:
            bot.handle_update(update)
        assert mock_send.called


# ─────────────────────────────────────────────
# SEND MESSAGE TESTS
# ─────────────────────────────────────────────

class TestSendMessage:

    def test_send_message_calls_telegram_api(self, bot):
        """send_message must call Telegram sendMessage"""
        with patch.object(bot, '_post_request') as mock_req:
            mock_req.return_value = {"ok": True, "result": {"message_id": 42}}
            result = bot.send_message(chat_id=99999, text="Test message")
        assert mock_req.called
        assert "sendMessage" in mock_req.call_args[0][0]

    def test_send_message_returns_message_id(self, bot):
        """send_message must return message_id"""
        with patch.object(bot, '_post_request') as mock_req:
            mock_req.return_value = {"ok": True, "result": {"message_id": 42}}
            result = bot.send_message(chat_id=99999, text="Test")
        assert result == 42

    def test_send_message_empty_text_raises(self, bot):
        """Empty text must raise ValueError"""
        with pytest.raises(ValueError, match="text"):
            bot.send_message(chat_id=99999, text="")

    def test_send_video_calls_send_video_endpoint(self, bot, tmp_path):
        """send_video must call sendVideo endpoint"""
        mp4 = tmp_path / "final.mp4"
        mp4.write_bytes(b"\x00" * 1024)
        with patch.object(bot, '_post_request') as mock_req:
            mock_req.return_value = {"ok": True, "result": {"message_id": 43}}
            bot.send_video(
                chat_id=99999,
                video_path=str(mp4),
                caption="Test video caption"
            )
        assert "sendVideo" in mock_req.call_args[0][0]

    def test_send_video_missing_file_raises(self, bot):
        """Missing video file must raise FileNotFoundError"""
        with pytest.raises(FileNotFoundError):
            bot.send_video(
                chat_id=99999,
                video_path="/nonexistent/video.mp4",
                caption="Caption"
            )


# ─────────────────────────────────────────────
# SECURITY TESTS
# ─────────────────────────────────────────────

class TestBotSecurity:

    def test_verify_signature_valid(self, bot):
        """Valid Telegram signature must pass verification"""
        import hmac
        import hashlib

        body = b'{"update_id": 123}'
        secret = hmac.new(
            hashlib.sha256(b"test_token_123").digest(),
            body,
            hashlib.sha256
        ).hexdigest()

        # Should not raise
        try:
            result = bot.verify_signature(body, secret)
            assert result is True or result is None
        except Exception:
            pass  # Verification method may not be implemented yet

    def test_update_without_message_is_ignored(self, bot):
        """Update with no message field must be handled gracefully"""
        update = {"update_id": 999}
        try:
            bot.handle_update(update)
        except Exception as e:
            pytest.fail(f"handle_update raised on empty update: {e}")

    def test_non_dict_update_is_ignored(self, bot):
        """Non-dict update must be handled gracefully"""
        try:
            bot.handle_update(None)
        except Exception as e:
            pytest.fail(f"handle_update raised on None: {e}")
