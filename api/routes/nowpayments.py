"""
HezCast Engine — NOWPayments Routes
Tinlance Limited | Apache 2.0

Endpoints:
  POST /billing/nowpayments/webhook  ← IPN from NOWPayments (sig verified)
  POST /billing/crypto-topup         ← Create crypto checkout invoice
  GET  /billing/crypto-currencies    ← List supported stablecoins
"""

import hashlib
import hmac
import json
import logging
import os
from fastapi import APIRouter, Request, HTTPException, Header
from pydantic import BaseModel, Field
from typing import Optional

from core.nowpayments import NOWPaymentsManager, SUPPORTED_CURRENCIES, TOPUP_PRICES
from core.transaction_log import get_transaction_log, DuplicateTransactionError
from core.billing import BillingManager

router  = APIRouter(tags=["Billing"])
logger  = logging.getLogger(__name__)

# IPN secret from NOWPayments dashboard → .env
IPN_SECRET = os.getenv("NOWPAYMENTS_IPN_SECRET", "")

# Lazy-init managers
_nowpayments = None
_billing     = None


def _get_nowpayments() -> NOWPaymentsManager:
    global _nowpayments
    if _nowpayments is None:
        try:
            _nowpayments = NOWPaymentsManager()
        except ValueError:
            # API key not set — create with empty key for endpoint availability
            _nowpayments = NOWPaymentsManager.__new__(NOWPaymentsManager)
            _nowpayments.api_key = ""
    return _nowpayments


def _get_billing() -> BillingManager:
    global _billing
    if _billing is None:
        _billing = BillingManager()
    return _billing


# ─────────────────────────────────────────────
# SCHEMAS
# ─────────────────────────────────────────────

VALID_CRYPTO_CURRENCIES = {c["id"] for c in SUPPORTED_CURRENCIES}
VOLATILE_CURRENCIES     = {"btc", "eth", "bnb", "sol", "ada", "xrp", "doge", "ltc"}

class CryptoTopupRequest(BaseModel):
    package:  str = Field(..., description="credits_50 or credits_100")
    currency: str = Field("usdttrc20", description="Stablecoin currency ID")

    def validate_currency(self):
        if self.currency.lower() in VOLATILE_CURRENCIES:
            raise ValueError(
                f"Volatile cryptocurrency '{self.currency}' not supported. "
                f"HezCast accepts stablecoins only: USDT, USDC, DAI"
            )
        if self.currency.lower() not in VALID_CRYPTO_CURRENCIES:
            raise ValueError(
                f"Currency '{self.currency}' not supported. "
                f"Supported: {sorted(VALID_CRYPTO_CURRENCIES)}"
            )


class CryptoTopupResponse(BaseModel):
    invoice_url:  str
    payment_id:   Optional[str] = None
    pay_currency: str
    price_amount: float
    package:      str
    credits:      int
    expires_at:   Optional[str] = None


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def process_nowpayments_event(payload: dict) -> None:
    """Process IPN event — separated for testability"""
    mgr     = _get_nowpayments()
    billing = _get_billing()
    mgr.process_payment(payload, billing)


def create_nowpayments_invoice(
    package:   str,
    currency:  str,
    tenant_id: str = "",
    email:     str = "",
) -> dict:
    """Create NOWPayments invoice — separated for testability"""
    mgr = _get_nowpayments()

    if package not in TOPUP_PRICES:
        raise ValueError(f"Unknown package: {package}")

    amount   = TOPUP_PRICES[package]
    credits  = 50 if package == "credits_50" else 100
    order_id = mgr.build_order_id(
        type="topup",
        package=package,
        tenant_id=tenant_id or "anonymous",
    )

    invoice = mgr.create_invoice(
        amount=amount,
        currency="usd",
        order_id=order_id,
        description=f"HezCast {credits} Credits",
        pay_currency=currency,
    )

    return invoice


# ─────────────────────────────────────────────
# ROUTES
# ─────────────────────────────────────────────

@router.post("/billing/nowpayments/webhook", status_code=200)
async def nowpayments_ipn_webhook(
    request: Request,
    x_nowpayments_sig: Optional[str] = Header(None, alias="x-nowpayments-sig"),
) -> dict:
    """
    Receive NOWPayments IPN (Instant Payment Notification).

    Verifies HMAC-SHA512 signature with IPN secret.
    Activates plan or adds credits on confirmed payment.

    Returns 403 on invalid/missing signature.
    Always returns 200 on success — NOWPayments retries on non-200.
    """
    body = await request.body()

    # Verify signature
    if not x_nowpayments_sig:
        logger.warning("NOWPayments IPN received without signature")
        raise HTTPException(status_code=403, detail="Missing x-nowpayments-sig header")

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    mgr = _get_nowpayments()
    if not mgr.verify_ipn_signature(payload, x_nowpayments_sig, IPN_SECRET):
        logger.warning(
            f"Invalid NOWPayments IPN signature | "
            f"sig={x_nowpayments_sig[:20]}..."
        )
        raise HTTPException(status_code=403, detail="Invalid IPN signature")

    # Process event
    event_type = payload.get("payment_status", "unknown")
    order_id   = payload.get("order_id", "")
    logger.info(f"NOWPayments IPN | status={event_type} | order={order_id}")

    try:
        # Idempotency check
        payment_id = payload.get("payment_id", "")
        if payment_id:
            tx_log = get_transaction_log()
            if tx_log.is_duplicate("nowpayments", str(payment_id)):
                logger.info(f"Duplicate NOWPayments IPN — skipping: {payment_id}")
                return {"ok": True, "status": event_type, "duplicate": True}

        process_nowpayments_event(payload)

        # Record transaction
        if payment_id:
            tx_log = get_transaction_log()
            order_id  = payload.get("order_id", "")
            tenant_id = order_id.split("_")[-1] if order_id else "unknown"
            try:
                tx_log.record({
                    "provider":       "nowpayments",
                    "provider_tx_id": str(payment_id),
                    "tenant_id":      tenant_id,
                    "amount_usd":     float(payload.get("price_amount", 0)),
                    "currency":       payload.get("pay_currency", ""),
                    "status":         event_type,
                    "event_type":     "crypto_payment",
                })
            except Exception as te:
                logger.warning(f"Could not record NP transaction: {te}")

        return {"ok": True, "status": event_type}
    except Exception as e:
        logger.error(f"NOWPayments IPN processing error: {e}")
        # Return 200 anyway — prevents NOWPayments from retrying indefinitely
        return {"ok": False, "error": str(e)}


@router.post("/billing/crypto-topup", response_model=CryptoTopupResponse)
async def crypto_topup(
    request_body: CryptoTopupRequest,
    request: Request,
) -> CryptoTopupResponse:
    """
    Create a NOWPayments crypto invoice for credit topup.

    Stablecoins only: USDT (TRC-20/ERC-20/BEP-20), USDC, DAI.
    BTC, ETH, and other volatile cryptocurrencies are rejected.

    Returns invoice URL to redirect user to NOWPayments checkout.
    """
    # Validate currency — reject volatile crypto
    currency = request_body.currency.lower()

    if currency in VOLATILE_CURRENCIES:
        raise HTTPException(
            status_code=422,
            detail=(
                f"'{request_body.currency}' is not accepted. "
                f"HezCast accepts stablecoins only: USDT, USDC, DAI. "
                f"Use the /billing/crypto-currencies endpoint to see supported options."
            )
        )

    if currency not in VALID_CRYPTO_CURRENCIES:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Currency '{request_body.currency}' is not supported. "
                f"Call GET /billing/crypto-currencies for the full list."
            )
        )

    if request_body.package not in TOPUP_PRICES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid package '{request_body.package}'. Valid: credits_50, credits_100"
        )

    # Get tenant info
    api_key   = request.headers.get("X-API-Key", "")
    from api.middleware.credit_gate import get_tenant_from_api_key
    tenant    = get_tenant_from_api_key(api_key)
    tenant_id = tenant["id"] if tenant else "anonymous"
    email     = tenant.get("email", "") if tenant else ""

    # Create invoice
    try:
        invoice = create_nowpayments_invoice(
            package=request_body.package,
            currency=currency,
            tenant_id=tenant_id,
            email=email,
        )
    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=f"Could not create payment invoice: {e}"
        )

    credits = 50 if request_body.package == "credits_50" else 100
    amount  = TOPUP_PRICES[request_body.package]

    return CryptoTopupResponse(
        invoice_url=  invoice.get("invoice_url", invoice.get("id", "")),
        payment_id=   str(invoice.get("id", "")),
        pay_currency= currency,
        price_amount= amount,
        package=      request_body.package,
        credits=      credits,
        expires_at=   invoice.get("expiration_estimate_date"),
    )


@router.get("/billing/crypto-currencies")
async def list_crypto_currencies() -> list:
    """
    List all supported crypto currencies for payment.

    Stablecoins only — USDT, USDC, DAI across multiple networks.
    Volatile cryptocurrencies (BTC, ETH, etc.) are not accepted.

    Public endpoint — no auth required.
    """
    return SUPPORTED_CURRENCIES
