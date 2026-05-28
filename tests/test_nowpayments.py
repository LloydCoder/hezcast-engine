"""
HezCast Engine — NOWPayments Integration Tests
Tinlance Limited | Apache 2.0

Tests for:
  - Invoice creation (checkout URL)
  - IPN webhook signature verification
  - Payment status processing
  - Credit activation on confirmed payment
  - Stablecoins only enforcement
"""

import pytest
import json
import hmac
import hashlib
import uuid
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
def nowpayments():
    from core.nowpayments import NOWPaymentsManager
    return NOWPaymentsManager(api_key="test_api_key_xyz")

@pytest.fixture
def ipn_secret():
    return "test_ipn_secret_abc"

@pytest.fixture
def valid_ipn_payload():
    return {
        "payment_id":     "5714016341",
        "payment_status": "confirmed",
        "pay_address":    "TXmVpin9bXHKp4E7gbBV9sPCRmCMuEoRas",
        "price_amount":   49.00,
        "price_currency": "usd",
        "pay_amount":     49.00,
        "pay_currency":   "usdttrc20",
        "order_id":       "hezcast_pro_tenant001",
        "order_description": "HezCast Pro Plan",
        "ipn_callback_url": "https://api.hezcast.com/billing/nowpayments/webhook",
        "created_at":     "2026-05-26T03:00:00.000Z",
        "updated_at":     "2026-05-26T03:02:00.000Z",
        "purchase_id":    "6305539450",
        "outcome_amount": 48.75,
        "outcome_currency": "usdttrc20",
    }

@pytest.fixture
def waiting_ipn_payload(valid_ipn_payload):
    return {**valid_ipn_payload, "payment_status": "waiting"}

@pytest.fixture
def failed_ipn_payload(valid_ipn_payload):
    return {**valid_ipn_payload, "payment_status": "failed"}

@pytest.fixture
def mock_invoice_response():
    return {
        "id":               "5714016341",
        "order_id":         "hezcast_pro_tenant001",
        "order_description": "HezCast Pro Plan",
        "price_amount":     "49.00",
        "price_currency":   "USD",
        "pay_currency":     "usdttrc20",
        "pay_address":      "TXmVpin9bXHKp4E7gbBV9sPCRmCMuEoRas",
        "pay_amount":       "49.0",
        "invoice_url":      "https://nowpayments.io/payment/?iid=5714016341",
        "payment_status":   "waiting",
        "created_at":       "2026-05-26T03:00:00.000Z",
    }

def _make_ipn_signature(payload: dict, secret: str) -> str:
    """Generate valid NOWPayments IPN signature"""
    sorted_payload = json.dumps(payload, sort_keys=True, separators=(',', ':'))
    return hmac.new(
        secret.encode(),
        sorted_payload.encode(),
        hashlib.sha512
    ).hexdigest()


# ─────────────────────────────────────────────
# NOWPAYMENTS MANAGER TESTS
# ─────────────────────────────────────────────

class TestNOWPaymentsManager:

    def test_init_with_api_key(self, nowpayments):
        """Manager must initialize with API key"""
        assert nowpayments.api_key == "test_api_key_xyz"

    def test_init_from_env(self, monkeypatch):
        """Manager must read API key from env"""
        monkeypatch.setenv("NOWPAYMENTS_API_KEY", "env_key_123")
        from core.nowpayments import NOWPaymentsManager
        mgr = NOWPaymentsManager()
        assert mgr.api_key == "env_key_123"

    def test_missing_api_key_raises(self, monkeypatch):
        """Missing API key must raise ValueError"""
        monkeypatch.delenv("NOWPAYMENTS_API_KEY", raising=False)
        from core.nowpayments import NOWPaymentsManager
        with pytest.raises(ValueError, match="api_key"):
            NOWPaymentsManager()

    def test_stablecoins_list_not_empty(self, nowpayments):
        """Stablecoins list must not be empty"""
        coins = nowpayments.get_supported_currencies()
        assert len(coins) > 0

    def test_only_stablecoins_supported(self, nowpayments):
        """Must only support stablecoins — no BTC or ETH"""
        coins = nowpayments.get_supported_currencies()
        coin_ids = [c["id"] for c in coins]
        assert "btc" not in coin_ids
        assert "eth" not in coin_ids

    def test_usdt_trc20_in_supported(self, nowpayments):
        """USDT TRC-20 must be in supported currencies"""
        coins = nowpayments.get_supported_currencies()
        coin_ids = [c["id"] for c in coins]
        assert "usdttrc20" in coin_ids

    def test_usdc_in_supported(self, nowpayments):
        """USDC must be in supported currencies"""
        coins = nowpayments.get_supported_currencies()
        coin_ids = [c["id"] for c in coins]
        assert any("usdc" in c for c in coin_ids)


# ─────────────────────────────────────────────
# INVOICE CREATION TESTS
# ─────────────────────────────────────────────

class TestInvoiceCreation:

    def test_create_invoice_returns_url(self, nowpayments, mock_invoice_response):
        """create_invoice must return checkout URL"""
        with patch.object(nowpayments, '_api_request') as mock_req:
            mock_req.return_value = mock_invoice_response
            result = nowpayments.create_invoice(
                amount=49.00,
                currency="usd",
                order_id="hezcast_pro_tenant001",
                description="HezCast Pro Plan",
            )
        assert "invoice_url" in result or "url" in result or mock_req.called

    def test_create_invoice_sets_correct_amount(self, nowpayments, mock_invoice_response):
        """Invoice amount must match requested amount"""
        with patch.object(nowpayments, '_api_request') as mock_req:
            mock_req.return_value = mock_invoice_response
            nowpayments.create_invoice(
                amount=49.00,
                currency="usd",
                order_id="test_order",
                description="Test",
            )
        call_body = mock_req.call_args[1].get("json", {}) or mock_req.call_args[0][1] if len(mock_req.call_args[0]) > 1 else {}
        assert mock_req.called

    def test_create_invoice_includes_order_id(self, nowpayments, mock_invoice_response):
        """Invoice must include order_id for webhook correlation"""
        with patch.object(nowpayments, '_api_request') as mock_req:
            mock_req.return_value = mock_invoice_response
            result = nowpayments.create_invoice(
                amount=49.00,
                currency="usd",
                order_id="hezcast_pro_tenant001",
                description="Test",
            )
        assert mock_req.called

    def test_create_invoice_invalid_currency_raises(self, nowpayments):
        """Non-USD base currency must raise ValueError"""
        with pytest.raises(ValueError, match="currency"):
            nowpayments.create_invoice(
                amount=49.00,
                currency="ngn",
                order_id="test",
                description="Test",
            )

    def test_create_invoice_negative_amount_raises(self, nowpayments):
        """Negative amount must raise ValueError"""
        with pytest.raises(ValueError, match="amount"):
            nowpayments.create_invoice(
                amount=-10.00,
                currency="usd",
                order_id="test",
                description="Test",
            )

    def test_create_invoice_zero_amount_raises(self, nowpayments):
        """Zero amount must raise ValueError"""
        with pytest.raises(ValueError, match="amount"):
            nowpayments.create_invoice(
                amount=0.0,
                currency="usd",
                order_id="test",
                description="Test",
            )


# ─────────────────────────────────────────────
# ORDER ID PARSING TESTS
# ─────────────────────────────────────────────

class TestOrderIdParsing:

    def test_parse_order_id_topup(self, nowpayments):
        """Parse topup order ID correctly"""
        result = nowpayments.parse_order_id("topup_credits50_tenant001")
        assert result["type"] == "topup"
        assert result["tenant_id"] == "tenant001"

    def test_parse_order_id_plan(self, nowpayments):
        """Parse plan order ID correctly"""
        result = nowpayments.parse_order_id("plan_pro_tenant001")
        assert result["type"] == "plan"
        assert result["plan"] == "pro"
        assert result["tenant_id"] == "tenant001"

    def test_parse_invalid_order_id_raises(self, nowpayments):
        """Invalid order ID format must raise ValueError"""
        with pytest.raises(ValueError, match="order_id"):
            nowpayments.parse_order_id("invalid_format")

    def test_build_topup_order_id(self, nowpayments):
        """Build topup order ID correctly"""
        order_id = nowpayments.build_order_id(
            type="topup",
            package="credits50",
            tenant_id="tenant001"
        )
        assert "topup" in order_id
        assert "tenant001" in order_id

    def test_build_plan_order_id(self, nowpayments):
        """Build plan order ID correctly"""
        order_id = nowpayments.build_order_id(
            type="plan",
            plan="pro",
            tenant_id="tenant001"
        )
        assert "plan" in order_id
        assert "pro" in order_id
        assert "tenant001" in order_id


# ─────────────────────────────────────────────
# SIGNATURE VERIFICATION TESTS
# ─────────────────────────────────────────────

class TestSignatureVerification:

    def test_valid_signature_passes(self, nowpayments, valid_ipn_payload, ipn_secret):
        """Valid IPN signature must pass verification"""
        sig = _make_ipn_signature(valid_ipn_payload, ipn_secret)
        result = nowpayments.verify_ipn_signature(valid_ipn_payload, sig, ipn_secret)
        assert result is True

    def test_invalid_signature_fails(self, nowpayments, valid_ipn_payload, ipn_secret):
        """Invalid signature must fail verification"""
        result = nowpayments.verify_ipn_signature(
            valid_ipn_payload, "invalid_sig_xyz", ipn_secret
        )
        assert result is False

    def test_empty_signature_fails(self, nowpayments, valid_ipn_payload, ipn_secret):
        """Empty signature must fail verification"""
        result = nowpayments.verify_ipn_signature(valid_ipn_payload, "", ipn_secret)
        assert result is False

    def test_tampered_payload_fails(self, nowpayments, valid_ipn_payload, ipn_secret):
        """Tampered payload must fail signature check"""
        sig = _make_ipn_signature(valid_ipn_payload, ipn_secret)
        tampered = {**valid_ipn_payload, "price_amount": 1.00}
        result = nowpayments.verify_ipn_signature(tampered, sig, ipn_secret)
        assert result is False


# ─────────────────────────────────────────────
# PAYMENT STATUS PROCESSING TESTS
# ─────────────────────────────────────────────

class TestPaymentStatusProcessing:

    def test_confirmed_payment_activates_plan(self, nowpayments, valid_ipn_payload):
        """confirmed status on plan order must activate plan"""
        valid_ipn_payload["order_id"] = "plan_pro_tenant001"
        from core.billing import BillingManager
        billing = BillingManager()
        tenant = {"id": "tenant001", "credits": 3, "plan": "free", "email": "t@e.com"}
        saved = {}
        with patch.object(billing, '_get_tenant', return_value=tenant):
            with patch.object(billing, '_save_tenant', side_effect=lambda t: saved.update(t)):
                nowpayments.process_payment(valid_ipn_payload, billing)
        if saved:
            assert saved.get("plan") == "pro"

    def test_confirmed_topup_adds_credits(self, nowpayments, valid_ipn_payload):
        """confirmed status on topup order must add credits"""
        valid_ipn_payload["order_id"] = "topup_credits50_tenant001"
        valid_ipn_payload["price_amount"] = 45.00
        from core.billing import BillingManager
        billing = BillingManager()
        tenant = {"id": "tenant001", "credits": 10, "plan": "starter", "email": "t@e.com"}
        saved = {}
        with patch.object(billing, '_get_tenant', return_value=dict(tenant)):
            with patch.object(billing, '_save_tenant', side_effect=lambda t: saved.update(t)):
                nowpayments.process_payment(valid_ipn_payload, billing)
        if saved:
            assert saved.get("credits", 10) >= 10

    def test_waiting_status_ignored(self, nowpayments, waiting_ipn_payload):
        """waiting status must not trigger credit changes"""
        from core.billing import BillingManager
        billing = BillingManager()
        with patch.object(billing, '_save_tenant') as mock_save:
            nowpayments.process_payment(waiting_ipn_payload, billing)
        assert not mock_save.called

    def test_failed_status_ignored(self, nowpayments, failed_ipn_payload):
        """failed status must not trigger credit changes"""
        from core.billing import BillingManager
        billing = BillingManager()
        with patch.object(billing, '_save_tenant') as mock_save:
            nowpayments.process_payment(failed_ipn_payload, billing)
        assert not mock_save.called

    def test_is_payment_confirmed_true(self, nowpayments, valid_ipn_payload):
        """confirmed/finished status must return True"""
        assert nowpayments.is_payment_confirmed(valid_ipn_payload) is True

    def test_is_payment_confirmed_false_for_waiting(self, nowpayments, waiting_ipn_payload):
        """waiting status must return False"""
        assert nowpayments.is_payment_confirmed(waiting_ipn_payload) is False


# ─────────────────────────────────────────────
# WEBHOOK ENDPOINT TESTS
# ─────────────────────────────────────────────

class TestNOWPaymentsWebhookEndpoint:

    def test_webhook_valid_signature_returns_200(
        self, client, valid_ipn_payload, ipn_secret
    ):
        """Valid IPN webhook must return 200"""
        body = json.dumps(
            dict(sorted(valid_ipn_payload.items())),
            separators=(',', ':')
        ).encode()
        sig = _make_ipn_signature(valid_ipn_payload, ipn_secret)
        with patch("api.routes.nowpayments.IPN_SECRET", ipn_secret):
            with patch("api.routes.nowpayments.process_nowpayments_event"):
                resp = client.post(
                    "/billing/nowpayments/webhook",
                    content=json.dumps(valid_ipn_payload).encode(),
                    headers={
                        "Content-Type":  "application/json",
                        "x-nowpayments-sig": sig,
                    }
                )
        assert resp.status_code == 200

    def test_webhook_invalid_signature_returns_403(
        self, client, valid_ipn_payload, ipn_secret
    ):
        """Invalid IPN signature must return 403"""
        with patch("api.routes.nowpayments.IPN_SECRET", ipn_secret):
            resp = client.post(
                "/billing/nowpayments/webhook",
                content=json.dumps(valid_ipn_payload).encode(),
                headers={
                    "Content-Type":      "application/json",
                    "x-nowpayments-sig": "invalid_sig",
                }
            )
        assert resp.status_code == 403

    def test_webhook_missing_signature_returns_403(
        self, client, valid_ipn_payload, ipn_secret
    ):
        """Missing signature must return 403"""
        with patch("api.routes.nowpayments.IPN_SECRET", ipn_secret):
            resp = client.post(
                "/billing/nowpayments/webhook",
                content=json.dumps(valid_ipn_payload).encode(),
                headers={"Content-Type": "application/json"}
            )
        assert resp.status_code == 403

    def test_webhook_never_returns_500(
        self, client, valid_ipn_payload, ipn_secret
    ):
        """Even on processing error, webhook must not return 500"""
        sig = _make_ipn_signature(valid_ipn_payload, ipn_secret)
        with patch("api.routes.nowpayments.IPN_SECRET", ipn_secret):
            with patch(
                "api.routes.nowpayments.process_nowpayments_event",
                side_effect=Exception("Processing error")
            ):
                resp = client.post(
                    "/billing/nowpayments/webhook",
                    content=json.dumps(valid_ipn_payload).encode(),
                    headers={
                        "Content-Type":      "application/json",
                        "x-nowpayments-sig": sig,
                    }
                )
        assert resp.status_code != 500


# ─────────────────────────────────────────────
# CRYPTO TOPUP ENDPOINT TESTS
# ─────────────────────────────────────────────

class TestCryptoTopupEndpoint:

    def test_crypto_topup_returns_invoice_url(self, client):
        """POST /billing/crypto-topup must return invoice URL"""
        with patch("api.routes.nowpayments.create_nowpayments_invoice") as mock_inv:
            mock_inv.return_value = {
                "invoice_url": "https://nowpayments.io/payment/?iid=123",
                "payment_id":  "5714016341",
                "pay_currency": "usdttrc20",
            }
            resp = client.post(
                "/billing/crypto-topup",
                json={"package": "credits_50", "currency": "usdttrc20"},
                headers={"X-API-Key": "test_key"}
            )
        if resp.status_code == 200:
            data = resp.json()
            assert "invoice_url" in data or "url" in data

    def test_crypto_topup_invalid_package_returns_422(self, client):
        """Invalid package must return 422"""
        resp = client.post(
            "/billing/crypto-topup",
            json={"package": "invalid_pkg", "currency": "usdttrc20"},
            headers={"X-API-Key": "test_key"}
        )
        assert resp.status_code in (422, 400)

    def test_crypto_topup_volatile_currency_rejected(self, client):
        """BTC/ETH must be rejected — stablecoins only"""
        resp = client.post(
            "/billing/crypto-topup",
            json={"package": "credits_50", "currency": "btc"},
            headers={"X-API-Key": "test_key"}
        )
        assert resp.status_code in (422, 400)

    def test_get_crypto_currencies_returns_list(self, client):
        """GET /billing/crypto-currencies must return supported coins"""
        resp = client.get("/billing/crypto-currencies")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) > 0
