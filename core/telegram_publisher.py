"""
HezCast Engine — Telegram Publisher
Tinlance Limited | Apache 2.0

Publishes generated videos + post bundles to Telegram channels.

Uses Telegram Bot API directly (no SDK dependency):
  sendVideo  → uploads MP4 with caption
  sendMessage → posts text-only updates

Controlled by env vars:
  TELEGRAM_BOT_TOKEN  → from @BotFather
  TELEGRAM_CHAT_ID    → channel username (@channel) or numeric ID

Optional — if env vars not set, publish calls return {"skipped": True}
so the pipeline never fails due to missing Telegram config.

Setup:
  1. Talk to @BotFather → create bot → get token
  2. Create Telegram channel → add bot as admin
  3. Get chat ID: https://api.telegram.org/bot<TOKEN>/getUpdates
  4. Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env
"""

import logging
import os
import requests
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"
CAPTION_LIMIT = 1024   # Telegram hard limit for video captions
MESSAGE_LIMIT = 4096   # Telegram hard limit for text messages


class TelegramPublisher:
    """
    Publishes HezCast output to a Telegram channel.

    Usage:
        # Explicit init
        publisher = TelegramPublisher(
            bot_token="123456:ABCdef...",
            chat_id="@mychannel"
        )

        # From env vars
        publisher = TelegramPublisher()

        # Publish video with bundle
        result = publisher.publish_video(
            video_path="/storage/outputs/job_id/final.mp4",
            bundle=post_bundle,
            platform="tiktok"
        )

        # Text-only post
        result = publisher.publish_text("🎬 New video just dropped!")
    """

    def __init__(
        self,
        bot_token: Optional[str] = None,
        chat_id:   Optional[str] = None,
    ):
        self.bot_token = bot_token or os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.chat_id   = chat_id   or os.getenv("TELEGRAM_CHAT_ID", "")

        # Validate only if args were explicitly passed
        if bot_token is not None and not self.bot_token:
            raise ValueError("bot_token must be a non-empty string")

        if (bot_token is not None or chat_id is not None):
            if not self.bot_token:
                raise ValueError("bot_token must be a non-empty string")
            if not self.chat_id:
                raise ValueError("chat_id must be a non-empty string")

        # Validate from env
        if bot_token is None and chat_id is None:
            env_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
            env_chat  = os.getenv("TELEGRAM_CHAT_ID",   "")
            if not env_token:
                raise ValueError(
                    "bot_token not provided and TELEGRAM_BOT_TOKEN env var not set"
                )
            if not env_chat:
                raise ValueError(
                    "chat_id not provided and TELEGRAM_CHAT_ID env var not set"
                )

        self.api_base_url = f"https://api.telegram.org/bot{self.bot_token}"

    # ─────────────────────────────────────────
    # PUBLIC API
    # ─────────────────────────────────────────

    def publish_video(
        self,
        video_path: str,
        bundle:     dict,
        platform:   str = "tiktok",
    ) -> dict:
        """
        Upload MP4 + caption to Telegram channel.

        Args:
            video_path: Path to the MP4 file
            bundle:     Post bundle from PostGenerator.generate()
            platform:   Which platform variant caption to use

        Returns:
            dict with: message_id, platform, published_at
            or {"skipped": True} if Telegram not configured

        Raises:
            FileNotFoundError:     If video file missing
            TelegramPublishError:  If Telegram API returns error
        """
        if not self.is_configured():
            logger.info("Telegram not configured — skipping publish")
            return {"skipped": True, "reason": "not_configured"}

        if not Path(video_path).exists():
            raise FileNotFoundError(f"Video file not found: {video_path}")

        caption = self.build_caption(bundle, platform)
        url     = f"{self.api_base_url}/sendVideo"

        logger.info(
            f"Publishing to Telegram | "
            f"chat={self.chat_id} | platform={platform} | "
            f"file={Path(video_path).name}"
        )

        with open(video_path, "rb") as video_file:
            response = self._post_request(
                url,
                data={
                    "chat_id":              self.chat_id,
                    "caption":              caption,
                    "parse_mode":           "HTML",
                    "supports_streaming":   True,
                },
                files={"video": video_file},
            )

        if not response.get("ok"):
            raise TelegramPublishError(
                f"Telegram API error: {response.get('description', 'Unknown error')} "
                f"(code {response.get('error_code', '?')})"
            )

        result_data = response["result"]
        message_id  = result_data["message_id"]

        logger.info(
            f"Published to Telegram ✓ | "
            f"message_id={message_id} | chat={self.chat_id}"
        )

        return {
            "message_id":   message_id,
            "chat_id":      self.chat_id,
            "platform":     platform,
            "published_at": datetime.now(timezone.utc).isoformat(),
        }

    def publish_text(self, text: str) -> dict:
        """
        Send a text-only message to the Telegram channel.

        Args:
            text: Message content (markdown/HTML supported)

        Returns:
            dict with: message_id, published_at

        Raises:
            ValueError:           If text is empty
            TelegramPublishError: If Telegram API returns error
        """
        if not text or not text.strip():
            raise ValueError("text must be a non-empty string")

        if not self.is_configured():
            return {"skipped": True, "reason": "not_configured"}

        # Truncate to Telegram message limit
        if len(text) > MESSAGE_LIMIT:
            text = text[:MESSAGE_LIMIT - 3] + "..."

        url = f"{self.api_base_url}/sendMessage"
        response = self._post_request(
            url,
            data={
                "chat_id":    self.chat_id,
                "text":       text,
                "parse_mode": "HTML",
            }
        )

        if not response.get("ok"):
            raise TelegramPublishError(
                f"Telegram sendMessage error: {response.get('description')}"
            )

        return {
            "message_id":   response["result"]["message_id"],
            "published_at": datetime.now(timezone.utc).isoformat(),
        }

    def build_caption(self, bundle: dict, platform: str = "tiktok") -> str:
        """
        Build a Telegram-ready caption from a post bundle.

        Uses the platform variant from bundle, appends CTA link,
        appends hashtags. Truncates to Telegram's 1024-char limit.

        Args:
            bundle:   Post bundle from PostGenerator
            platform: tiktok | instagram | linkedin

        Returns:
            Caption string (max 1024 chars)
        """
        variants = bundle.get("platform_variants", {})

        # Get platform-specific variant, fallback to tiktok, then caption
        base = (
            variants.get(platform)
            or variants.get("tiktok")
            or bundle.get("caption", "")
        )

        cta_link = bundle.get("cta_link", "")
        hashtags = bundle.get("hashtags", [])

        # Build caption parts
        parts = [base]

        if cta_link and cta_link not in base:
            parts.append(f"\n\n{cta_link}")

        if hashtags:
            # Use first 5 hashtags to stay concise
            tag_str = " ".join(hashtags[:5])
            if tag_str not in base:
                parts.append(f"\n{tag_str}")

        caption = "".join(parts)

        # Hard truncate to Telegram limit
        if len(caption) > CAPTION_LIMIT:
            caption = caption[:CAPTION_LIMIT - 3] + "..."

        return caption

    def is_configured(self) -> bool:
        """Return True if bot_token and chat_id are both set"""
        return bool(self.bot_token and self.chat_id)

    # ─────────────────────────────────────────
    # HTTP (mockable in tests)
    # ─────────────────────────────────────────

    def _post_request(
        self,
        url:   str,
        data:  Optional[dict] = None,
        files: Optional[dict] = None,
    ) -> dict:
        """
        Make POST request to Telegram API.
        Mocked in tests via patch('core.telegram_publisher.TelegramPublisher._post_request').

        Raises:
            TelegramPublishError: On network error or timeout
        """
        try:
            resp = requests.post(
                url,
                data=data,
                files=files,
                timeout=120,   # 2 min — large video uploads need time
            )
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.Timeout:
            raise TelegramPublishError("Telegram API request timed out")
        except requests.exceptions.ConnectionError as e:
            raise TelegramPublishError(f"Telegram API connection error: {e}")
        except requests.exceptions.HTTPError as e:
            raise TelegramPublishError(f"Telegram HTTP error: {e}")


# ─────────────────────────────────────────────
# EXCEPTIONS
# ─────────────────────────────────────────────

class TelegramPublishError(Exception):
    """Raised when Telegram API returns an error or times out"""
    pass
