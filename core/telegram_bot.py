"""
HezCast Engine — Telegram Bot
Tinlance Limited | Apache 2.0

Bidirectional Telegram interface for HezCast.

Full conversation flow:
  1. You:  /generate GiftMode forgot birthday gift
  2. Bot:  ⚡ Job started — abc12345
           Generating 5 hook variants...

  3. Bot:  🎬 Hook variants ready — pick one:
           1. Nobody told me you could forget TWICE...
           2. I had 2 hours to find a gift. Cooked.
           3. POV: Her birthday is TODAY.
           4. The gift panic is real.
           5. She said it's fine. It wasn't.
           → Reply: /select abc12345 [1-5]

  4. You:  /select abc12345 2
  5. Bot:  🔄 Rendering hook 2 for GiftMode...
           Script → Voice → Clips → Compose → QA
           [~2 minutes]

  6. Bot:  ✅ Video ready!
           [MP4 file]
           📋 Caption: I had 2 hours to find a gift...
           #GiftMode #GiftIdeas #BirthdayGift
           🔗 https://giftmode.app

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

import json
import logging
import os
import re
import requests
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"
MAX_MESSAGE_LEN = 4096
MAX_CAPTION_LEN = 1024

VALID_BRANDS = {"GiftMode", "Tinlance", "WebTemify", "HezCast"}
BRAND_ALIASES = {
    "giftmode": "GiftMode",
    "gift":     "GiftMode",
    "tinlance": "Tinlance",
    "tin":      "Tinlance",
    "webtemify":"WebTemify",
    "web":      "WebTemify",
    "hezcast":  "HezCast",
    "hez":      "HezCast",
}


class HezCastBot:
    """
    Telegram bot for HezCast Engine.

    Handles bidirectional video generation:
    Telegram message → parse command → dispatch to API → reply with MP4

    Usage:
        bot = HezCastBot()  # reads from env
        bot.handle_update(telegram_update_dict)
    """

    def __init__(
        self,
        bot_token: Optional[str] = None,
        chat_id:   Optional[str] = None,
    ):
        self.bot_token = bot_token or os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.chat_id   = chat_id   or os.getenv("TELEGRAM_CHAT_ID", "")
        self.api_base  = f"https://api.telegram.org/bot{self.bot_token}"

        # Internal job store reference (shared with API layer)
        self._jobs  = {}
        self._hooks = {}

        try:
            from api.routes.generate import _jobs, _hooks_store
            self._jobs  = _jobs
            self._hooks = _hooks_store
        except ImportError:
            pass

    # ─────────────────────────────────────────
    # MAIN HANDLER
    # ─────────────────────────────────────────

    def handle_update(self, update: dict) -> None:
        """
        Process a Telegram update object.
        Entry point called by the webhook route.
        Never raises — all errors are caught and replied to user.
        """
        if not update or not isinstance(update, dict):
            return

        message = self.extract_message(update)
        if not message:
            return

        chat_id = self.extract_chat_id(update)
        text    = message.get("text", "").strip()

        if not text or not text.startswith("/"):
            return

        try:
            cmd = self.parse_command(text)
            self._route_command(cmd, chat_id, update)
        except Exception as e:
            logger.error(f"Bot handler error: {e}")
            try:
                self.send_message(
                    chat_id=chat_id,
                    text=self.build_reply_error(str(e), "unknown")
                )
            except Exception:
                pass

    def _route_command(self, cmd: dict, chat_id: int, update: dict) -> None:
        """Route parsed command to the correct handler"""
        command = cmd.get("command", "unknown")

        if command == "generate":
            self._handle_generate(cmd, chat_id)
        elif command == "select":
            self._handle_select(cmd, chat_id)
        elif command == "status":
            self._handle_status(cmd, chat_id)
        elif command == "brands":
            self.send_message(chat_id, self.build_reply_brands())
        elif command == "credits":
            self._handle_credits(chat_id)
        elif command == "help":
            self.send_message(chat_id, self.build_reply_help())
        elif command == "cancel":
            self._handle_cancel(cmd, chat_id)
        else:
            self.send_message(chat_id, self.build_reply_help())

    # ─────────────────────────────────────────
    # COMMAND HANDLERS
    # ─────────────────────────────────────────

    def _handle_generate(self, cmd: dict, chat_id: int) -> None:
        """Handle /generate command — dispatch job, reply with confirmation"""
        brand = cmd.get("brand", "")
        topic = cmd.get("topic", "")
        url   = cmd.get("url", "")

        if not brand:
            self.send_message(
                chat_id,
                "❌ Missing brand.\n\n"
                "Usage: /generate [brand] [topic]\n"
                "Brands: GiftMode · Tinlance · WebTemify · HezCast"
            )
            return

        if not topic and not url:
            self.send_message(
                chat_id,
                f"❌ Missing topic or URL.\n\n"
                f"Usage: /generate {brand} your topic here\n"
                f"Or:    /generate {brand} --url https://yoursite.com/blog"
            )
            return

        # Dispatch to pipeline
        result = self._dispatch_generate(
            brand=brand, topic=topic, url=url
        )

        job_id = result.get("job_id", "unknown")

        # Send confirmation
        self.send_message(
            chat_id,
            self.build_reply_job_started(job_id, brand, topic or url)
        )

        # If hooks are already available (sync mode), send them
        if job_id in self._hooks and self._hooks[job_id]:
            self.send_message(
                chat_id,
                self.build_reply_hooks(job_id, self._hooks[job_id])
            )

    def _handle_select(self, cmd: dict, chat_id: int) -> None:
        """Handle /select command — trigger render, reply with progress"""
        job_id      = cmd.get("job_id", "")
        variant_num = cmd.get("variant_num")

        if not job_id or variant_num is None:
            self.send_message(
                chat_id,
                "❌ Usage: /select [job_id] [variant_num]\n"
                "Example: /select abc12345 2"
            )
            return

        result = self._dispatch_select(job_id=job_id, variant_num=variant_num)

        self.send_message(
            chat_id,
            self.build_reply_processing(job_id, variant_num)
        )

    def _handle_status(self, cmd: dict, chat_id: int) -> None:
        """Handle /status command — reply with current job state"""
        job_id = cmd.get("job_id", "")

        if not job_id:
            self.send_message(
                chat_id,
                "❌ Usage: /status [job_id]\nExample: /status abc12345"
            )
            return

        job = self._dispatch_status(job_id=job_id)

        if not job:
            self.send_message(chat_id, f"❌ Job not found: `{job_id}`")
            return

        self.send_message(chat_id, self.build_reply_status(job))

        # If completed, send the video
        if job.get("status") == "completed" and job.get("output_path"):
            try:
                bundle = {
                    "caption":  job.get("topic", ""),
                    "hashtags": [],
                    "cta_link": "",
                    "platform_variants": {"tiktok": job.get("topic", "")}
                }
                from core.telegram_publisher import TelegramPublisher
                pub = TelegramPublisher(
                    bot_token=self.bot_token,
                    chat_id=str(chat_id)
                )
                pub.publish_video(
                    video_path=job["output_path"],
                    bundle=bundle,
                    platform="tiktok"
                )
            except Exception as e:
                logger.warning(f"Could not send video via status: {e}")

    def _handle_credits(self, chat_id: int) -> None:
        """Handle /credits command"""
        self.send_message(
            chat_id,
            "💳 *Credits*\n\n"
            "Free plan: 3 videos/month\n"
            "Starter ($19/mo): 15 videos\n"
            "Pro ($49/mo): 60 videos\n"
            "Agency ($149/mo): 300 videos\n\n"
            "→ cast.tinlance.com/pricing"
        )

    def _handle_cancel(self, cmd: dict, chat_id: int) -> None:
        """Handle /cancel command"""
        job_id = cmd.get("job_id", "")
        if job_id and job_id in self._jobs:
            self._jobs[job_id]["status"] = "cancelled"
            self.send_message(chat_id, f"✓ Job `{job_id}` cancelled.")
        else:
            self.send_message(chat_id, f"❌ Job not found: `{job_id}`")

    # ─────────────────────────────────────────
    # DISPATCHERS (mockable in tests)
    # ─────────────────────────────────────────

    def _dispatch_generate(
        self, brand: str, topic: str, url: str = ""
    ) -> dict:
        """Dispatch generate job to pipeline. Mockable in tests."""
        from api.routes.generate import submit_job
        from api.schemas import GenerateRequest

        request = GenerateRequest(
            topic=topic or None,
            url=url or None,
            brand=brand,
        )
        return submit_job(request)

    def _dispatch_select(self, job_id: str, variant_num: int) -> dict:
        """Dispatch hook selection to pipeline. Mockable in tests."""
        from api.routes.hooks import select_hook_and_render
        return select_hook_and_render(job_id, variant_num) or {}

    def _dispatch_status(self, job_id: str) -> Optional[dict]:
        """Fetch job status. Mockable in tests."""
        from api.routes.status import get_job
        return get_job(job_id)

    # ─────────────────────────────────────────
    # COMMAND PARSER
    # ─────────────────────────────────────────

    def parse_command(self, text: str) -> dict:
        """
        Parse a Telegram bot command string into a structured dict.

        Returns dict with at minimum: {"command": str}
        """
        if not text or not isinstance(text, str):
            return {"command": "unknown", "raw": text}

        text = text.strip()

        # Extract command (handle /cmd@botname format)
        match = re.match(r'^/(\w+)(?:@\w+)?(.*)$', text, re.DOTALL)
        if not match:
            return {"command": "unknown", "raw": text}

        cmd_name = match.group(1).lower()
        rest     = match.group(2).strip()

        # ── /generate [brand] [topic] or [brand] --url [url]
        if cmd_name == "generate":
            parts = rest.split(None, 1)
            if not parts:
                return {"command": "generate", "brand": "", "topic": "", "url": ""}

            brand_raw = parts[0]
            brand     = self._resolve_brand(brand_raw)
            remainder = parts[1] if len(parts) > 1 else ""

            # Check for --url flag
            url_match = re.search(r'--url\s+(https?://\S+)', remainder)
            if url_match:
                return {
                    "command": "generate",
                    "brand":   brand,
                    "topic":   "",
                    "url":     url_match.group(1),
                }

            return {
                "command": "generate",
                "brand":   brand,
                "topic":   remainder.strip(),
                "url":     "",
            }

        # ── /select [job_id] [variant_num]
        elif cmd_name == "select":
            parts = rest.split()
            if len(parts) < 2:
                return {
                    "command":     "error",
                    "message":     "Usage: /select [job_id] [variant_num]",
                    "variant_num": None,
                }
            try:
                variant = int(parts[1])
                if variant < 1:
                    return {"command": "error", "message": "variant_num must be >= 1"}
                return {
                    "command":     "select",
                    "job_id":      parts[0],
                    "variant_num": variant,
                }
            except ValueError:
                return {"command": "error", "message": "variant_num must be a number"}

        # ── /status [job_id]
        elif cmd_name == "status":
            parts = rest.split()
            return {
                "command": "status",
                "job_id":  parts[0] if parts else "",
            }

        # ── /cancel [job_id]
        elif cmd_name == "cancel":
            parts = rest.split()
            return {
                "command": "cancel",
                "job_id":  parts[0] if parts else "",
            }

        # ── Simple commands
        elif cmd_name in ("brands", "credits", "help", "start"):
            return {"command": cmd_name if cmd_name != "start" else "help"}

        else:
            return {"command": "unknown", "raw": text}

    def _resolve_brand(self, raw: str) -> str:
        """Resolve brand name case-insensitively"""
        return BRAND_ALIASES.get(raw.lower(), raw)

    # ─────────────────────────────────────────
    # REPLY BUILDERS
    # ─────────────────────────────────────────

    def build_reply_job_started(
        self, job_id: str, brand: str, topic: str
    ) -> str:
        topic_preview = (topic[:50] + "...") if len(topic) > 50 else topic
        return (
            f"⚡ *Job started*\n\n"
            f"Brand: {brand}\n"
            f"Topic: {topic_preview}\n"
            f"Job ID: `{job_id}`\n\n"
            f"Generating hook variants...\n"
            f"I'll send your options in a moment."
        )

    def build_reply_hooks(self, job_id: str, hooks: list) -> str:
        lines = [f"🎬 *Hook variants ready — pick one:*\n"]
        for h in hooks:
            num  = h.get("variant_num", "?")
            text = h.get("hook_text", "")
            lines.append(f"{num}. {text}")
        lines.append(f"\n→ Reply: `/select {job_id} [1-{len(hooks)}]`")
        return self._truncate("\n".join(lines))

    def build_reply_processing(self, job_id: str, variant_num: int) -> str:
        return (
            f"🔄 *Rendering hook {variant_num}...*\n\n"
            f"Job ID: `{job_id}`\n\n"
            f"Pipeline: Script → Voice → Clips → Compose → QA\n"
            f"Estimated time: ~2 minutes\n\n"
            f"Check progress: `/status {job_id}`"
        )

    def build_reply_completed(
        self,
        job_id: str,
        output_path: str,
        caption: str,
        duration_sec: float,
    ) -> str:
        dur = f"{duration_sec:.1f}s" if duration_sec else "—"
        return (
            f"✅ *Video ready!*\n\n"
            f"Job ID: `{job_id}`\n"
            f"Duration: {dur}\n"
            f"Format: 1080×1920 MP4\n\n"
            f"📋 {caption[:200] if caption else 'No caption'}"
        )

    def build_reply_status(self, job: dict) -> str:
        status  = job.get("status", "unknown")
        job_id  = job.get("job_id", "?")
        brand   = job.get("brand", "?")
        topic   = job.get("topic", "")[:40]

        status_icons = {
            "queued":             "⏳ Queued",
            "generating_hooks":   "✍️  Generating hooks",
            "awaiting_selection": "👆 Waiting for hook selection",
            "processing":         "🎙️  Processing voice",
            "composing":          "🎬 Composing video",
            "qa_check":           "🔍 QA validation",
            "completed":          "✅ Complete",
            "failed":             "❌ Failed",
            "needs_review":       "⚠️  Needs review",
        }

        status_display = status_icons.get(status, f"• {status}")

        lines = [
            f"📊 *Job Status*\n",
            f"ID:     `{job_id}`",
            f"Brand:  {brand}",
            f"Topic:  {topic}",
            f"Status: {status_display}",
        ]

        if job.get("error_message"):
            lines.append(f"Error:  {job['error_message'][:100]}")

        if job.get("duration_sec"):
            lines.append(f"Length: {job['duration_sec']:.1f}s")

        if job.get("render_time_ms"):
            lines.append(f"Render: {job['render_time_ms']/1000:.1f}s")

        return self._truncate("\n".join(lines))

    def build_reply_brands(self) -> str:
        return (
            "🎭 *Available Brands*\n\n"
            "• *GiftMode* — emotional UGC, 5 hooks, 25s\n"
            "  Consumer gifting app\n\n"
            "• *Tinlance* — authority, 3 hooks, 30s\n"
            "  AI & cybersecurity engineering\n\n"
            "• *WebTemify* — developer energy, 4 hooks, 22s\n"
            "  Website template marketplace\n\n"
            "• *HezCast* — founder energy, 5 hooks, 25s\n"
            "  AI content broadcasting system\n\n"
            "Usage: /generate [brand] [topic]"
        )

    def build_reply_help(self) -> str:
        return (
            "⚡ *HezCast Bot — Commands*\n\n"
            "*/generate* [brand] [topic]\n"
            "Generate a video from a topic\n"
            "Example: `/generate GiftMode forgot birthday gift`\n\n"
            "*/generate* [brand] --url [url]\n"
            "Generate a video from a URL\n"
            "Example: `/generate Tinlance --url https://tinlance.com/blog`\n\n"
            "*/select* [job\\_id] [1-5]\n"
            "Select a hook variant to render\n"
            "Example: `/select abc12345 2`\n\n"
            "*/status* [job\\_id]\n"
            "Check job progress\n\n"
            "*/brands*\n"
            "List available brands\n\n"
            "*/credits*\n"
            "View plan and credit balance\n\n"
            "*/cancel* [job\\_id]\n"
            "Cancel a queued job\n\n"
            "*/help*\n"
            "Show this message\n\n"
            "─────────────────\n"
            "_HezCast by Tinlance — cast.tinlance.com_"
        )

    def build_reply_error(self, error_message: str, command: str) -> str:
        return (
            f"❌ *Something went wrong*\n\n"
            f"Command: /{command}\n"
            f"Error: {error_message[:200]}\n\n"
            f"Try /help for usage instructions."
        )

    # ─────────────────────────────────────────
    # SEND METHODS
    # ─────────────────────────────────────────

    def send_message(self, chat_id: int, text: str) -> int:
        """Send a text message. Returns message_id."""
        if not text or not str(text).strip():
            raise ValueError("text must be a non-empty string")

        text = self._truncate(str(text))
        url  = f"{self.api_base}/sendMessage"

        response = self._post_request(
            url,
            data={
                "chat_id":    chat_id,
                "text":       text,
                "parse_mode": "Markdown",
            }
        )

        if not response.get("ok"):
            logger.warning(
                f"sendMessage failed: {response.get('description')}"
            )
            return 0

        return response["result"]["message_id"]

    def send_video(
        self,
        chat_id: int,
        video_path: str,
        caption: str = "",
    ) -> int:
        """Send an MP4 video file. Returns message_id."""
        if not Path(video_path).exists():
            raise FileNotFoundError(f"Video not found: {video_path}")

        caption = caption[:MAX_CAPTION_LEN] if caption else ""
        url     = f"{self.api_base}/sendVideo"

        with open(video_path, "rb") as vf:
            response = self._post_request(
                url,
                data={
                    "chat_id":            chat_id,
                    "caption":            caption,
                    "parse_mode":         "Markdown",
                    "supports_streaming": True,
                },
                files={"video": vf}
            )

        if not response.get("ok"):
            logger.warning(
                f"sendVideo failed: {response.get('description')}"
            )
            return 0

        return response["result"]["message_id"]

    # ─────────────────────────────────────────
    # EXTRACT HELPERS
    # ─────────────────────────────────────────

    def extract_message(self, update: dict) -> Optional[dict]:
        if not update or not isinstance(update, dict):
            return None
        return update.get("message") or update.get("edited_message")

    def extract_chat_id(self, update: dict) -> int:
        message = self.extract_message(update)
        if message:
            return message.get("chat", {}).get("id", 0)
        return 0

    def extract_user(self, update: dict) -> Optional[dict]:
        message = self.extract_message(update)
        if message:
            return message.get("from")
        return None

    # ─────────────────────────────────────────
    # SECURITY
    # ─────────────────────────────────────────

    def verify_signature(self, body: bytes, signature: str) -> bool:
        """
        Verify Telegram webhook signature.
        Uses HMAC-SHA256 with SHA256 hash of bot token as secret.
        """
        import hmac
        import hashlib
        try:
            secret = hmac.new(
                hashlib.sha256(self.bot_token.encode()).digest(),
                body,
                hashlib.sha256
            ).hexdigest()
            return hmac.compare_digest(secret, signature)
        except Exception:
            return False

    # ─────────────────────────────────────────
    # HTTP (mockable in tests)
    # ─────────────────────────────────────────

    def _post_request(
        self,
        url: str,
        data: Optional[dict] = None,
        files: Optional[dict] = None,
    ) -> dict:
        """Make POST to Telegram API. Mocked in tests."""
        try:
            resp = requests.post(url, data=data, files=files, timeout=60)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"Telegram API error: {e}")
            return {"ok": False, "description": str(e)}

    # ─────────────────────────────────────────
    # HELPERS
    # ─────────────────────────────────────────

    def _truncate(self, text: str) -> str:
        """Truncate to Telegram message limit"""
        if len(text) > MAX_MESSAGE_LEN:
            return text[:MAX_MESSAGE_LEN - 3] + "..."
        return text
