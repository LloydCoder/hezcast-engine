"""
HezCast Engine — Telegram Webhook Route
Tinlance Limited | Apache 2.0

Receives Telegram updates via webhook POST and dispatches
to HezCastBot for processing.

CRITICAL: This endpoint must ALWAYS return 200.
If it returns anything else, Telegram will retry the update
indefinitely, causing duplicate job submissions.

Setup:
  1. Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env
  2. Register webhook with Telegram:
     curl "https://api.telegram.org/bot<TOKEN>/setWebhook?url=https://cast.tinlance.com/telegram/webhook"
  3. Verify: GET /telegram/webhook/info
"""

import logging
import os
from fastapi import APIRouter, Request, Response
from typing import Any

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Telegram"])

# Lazy-init bot instance
_bot = None


def _get_bot():
    """Lazy-initialize HezCastBot singleton"""
    global _bot
    if _bot is None:
        from core.telegram_bot import HezCastBot
        _bot = HezCastBot()
    return _bot


def process_update(update: dict) -> None:
    """
    Process a Telegram update.
    Separated from route handler for testability.
    """
    bot = _get_bot()
    bot.handle_update(update)


def get_webhook_info() -> dict:
    """
    Return current webhook configuration status.
    Separated for testability.
    """
    token   = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")

    return {
        "configured":     bool(token and chat_id),
        "bot_token_set":  bool(token),
        "chat_id_set":    bool(chat_id),
        "chat_id":        chat_id if chat_id else None,
    }


@router.post("/telegram/webhook")
async def telegram_webhook(request: Request) -> dict:
    """
    Receive Telegram webhook updates.

    ALWAYS returns {"ok": true} with HTTP 200.
    Processing errors are logged but never surfaced to Telegram.
    """
    try:
        body = await request.body()

        # Parse JSON body
        try:
            update = await request.json()
        except Exception:
            logger.warning("Telegram webhook received non-JSON body")
            return {"ok": True}

        # Process update (never raises)
        try:
            process_update(update)
        except Exception as e:
            logger.error(f"Telegram update processing error: {e}")

    except Exception as e:
        logger.error(f"Telegram webhook handler error: {e}")

    # ALWAYS return 200 OK
    return {"ok": True}


@router.get("/telegram/webhook/info")
async def telegram_webhook_info() -> dict:
    """
    Check Telegram bot configuration status.
    Safe to call anytime — no side effects.
    """
    return get_webhook_info()


@router.post("/telegram/webhook/register")
async def register_webhook(request: Request) -> dict:
    """
    Register this server as the Telegram webhook.
    Requires DOMAIN to be set in .env.

    Body: {"domain": "cast.tinlance.com"} (optional — falls back to DOMAIN env)
    """
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    if not token:
        return {"ok": False, "error": "TELEGRAM_BOT_TOKEN not configured"}

    try:
        body   = await request.json()
        domain = body.get("domain") or os.getenv("DOMAIN", "")
    except Exception:
        domain = os.getenv("DOMAIN", "")

    if not domain:
        return {
            "ok":    False,
            "error": "Domain not provided. Set DOMAIN in .env or pass in request body."
        }

    webhook_url = f"https://{domain}/telegram/webhook"

    import requests as req
    try:
        resp = req.get(
            f"https://api.telegram.org/bot{token}/setWebhook",
            params={"url": webhook_url},
            timeout=10
        )
        data = resp.json()
        if data.get("ok"):
            logger.info(f"Telegram webhook registered: {webhook_url}")
            return {"ok": True, "webhook_url": webhook_url}
        else:
            return {"ok": False, "error": data.get("description")}
    except Exception as e:
        return {"ok": False, "error": str(e)}
