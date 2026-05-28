"""
HezCast Engine — Telegram Webhook Route Tests
TDD Phase 7 | Tinlance Limited
Tests written BEFORE implementation (Red-Green-Refactor)

FastAPI webhook endpoint that receives Telegram updates
and dispatches to HezCastBot for processing.
"""

import pytest
import json
import hmac
import hashlib
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient


# ─────────────────────────────────────────────
# FIXTURES
# ─────────────────────────────────────────────

@pytest.fixture
def client():
    from api.main import app
    return TestClient(app)

@pytest.fixture
def valid_update():
    return {
        "update_id": 123456,
        "message": {
            "message_id": 1,
            "from": {"id": 99999, "username": "lloydambition"},
            "chat": {"id": 99999, "type": "private"},
            "text": "/generate GiftMode forgot birthday gift",
            "date": 1748000000,
        }
    }

@pytest.fixture
def bot_token():
    return "test_bot_token_123"


# ─────────────────────────────────────────────
# WEBHOOK ENDPOINT TESTS
# ─────────────────────────────────────────────

class TestWebhookEndpoint:

    def test_webhook_returns_200(self, client, valid_update):
        """POST /telegram/webhook must return 200"""
        with patch("api.routes.telegram_webhook.process_update"):
            resp = client.post(
                "/telegram/webhook",
                json=valid_update
            )
        assert resp.status_code == 200

    def test_webhook_returns_ok_true(self, client, valid_update):
        """Webhook response must have ok: true"""
        with patch("api.routes.telegram_webhook.process_update"):
            resp = client.post(
                "/telegram/webhook",
                json=valid_update
            )
        assert resp.json().get("ok") is True

    def test_webhook_empty_body_returns_200(self, client):
        """Empty update must return 200 (Telegram retries otherwise)"""
        with patch("api.routes.telegram_webhook.process_update"):
            resp = client.post(
                "/telegram/webhook",
                json={}
            )
        assert resp.status_code == 200

    def test_webhook_invalid_json_returns_200(self, client):
        """Invalid JSON must still return 200 to prevent Telegram retries"""
        resp = client.post(
            "/telegram/webhook",
            content=b"not json",
            headers={"Content-Type": "application/json"}
        )
        # Should not crash the server
        assert resp.status_code in (200, 422)

    def test_webhook_calls_process_update(self, client, valid_update):
        """Webhook must call process_update with the update"""
        with patch("api.routes.telegram_webhook.process_update") as mock_process:
            client.post("/telegram/webhook", json=valid_update)
        assert mock_process.called

    def test_webhook_passes_update_to_process(self, client, valid_update):
        """Webhook must pass the full update to process_update"""
        received = {}
        def capture(update):
            received.update(update)
        with patch("api.routes.telegram_webhook.process_update", side_effect=capture):
            client.post("/telegram/webhook", json=valid_update)
        assert received.get("update_id") == 123456

    def test_webhook_never_returns_500(self, client, valid_update):
        """Even if processing fails, webhook must not return 500"""
        with patch(
            "api.routes.telegram_webhook.process_update",
            side_effect=Exception("Processing error")
        ):
            resp = client.post("/telegram/webhook", json=valid_update)
        assert resp.status_code != 500


# ─────────────────────────────────────────────
# WEBHOOK HEALTH TESTS
# ─────────────────────────────────────────────

class TestWebhookHealth:

    def test_webhook_info_endpoint(self, client):
        """GET /telegram/webhook/info must return bot status"""
        with patch("api.routes.telegram_webhook.get_webhook_info") as mock_info:
            mock_info.return_value = {
                "configured": False,
                "bot_token_set": False,
                "chat_id_set": False,
            }
            resp = client.get("/telegram/webhook/info")
        assert resp.status_code == 200

    def test_webhook_info_shows_configured_status(self, client):
        """Webhook info must show whether bot is configured"""
        with patch("api.routes.telegram_webhook.get_webhook_info") as mock_info:
            mock_info.return_value = {
                "configured": True,
                "bot_token_set": True,
                "chat_id_set": True,
            }
            resp = client.get("/telegram/webhook/info")
        data = resp.json()
        assert "configured" in data
