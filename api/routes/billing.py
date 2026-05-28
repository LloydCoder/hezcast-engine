"""
HezCast Engine — Billing Routes
Tinlance Limited | Apache 2.0

Endpoints:
  POST /billing/webhook   ← LemonSqueezy webhook (signature verified)
  POST /billing/topup     ← Generate checkout URL for credit topup
  GET  /billing/balance   ← Get current credit balance + plan
  GET  /billing/plans     ← List all available plans
"""

import hashlib
import hmac
import json
import logging
import os
from fastapi import APIRouter, Request, HTTPException, Header
from pydantic import BaseModel, Field
from typing import Optional

from core.billing import BillingManager, TOPUP_PACKAGES
from core.transaction_log import get_transaction_log, DuplicateTransactionError

router  = APIRouter(tags=["Billing"])
logger  = logging.getLogger(__name__)
billing = BillingManager()

# LemonSqueezy webhook secret — set in .env
WEBHOOK_SECRET = os.getenv("LEMONSQUEEZY_WEBHOOK_SECRET", "")


# ─────────────────────────────────────────────
# SCHEMAS
# ─────────────────────────────────────────────

class TopupRequest(BaseModel):
    package: str = Field(..., description="credits_50 or credits_100")

    def validate_package(self):
        if self.package not in TOPUP_PACKAGES:
            raise ValueError(
                f"Unknown package '{self.package}'. "
                f"Valid: {list(TOPUP_PACKAGES.keys())}"
            )


class TopupResponse(BaseModel):
    checkout_url:  str
    package:       str
    credits:       int
    price_dollars: float


class BalanceResponse(BaseModel):
    credits:      int
    plan:         str
    plan_name:    str
    monthly_alloc: int


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def _verify_lemonsqueezy_signature(
    body: bytes,
    signature: str,
    secret: str
) -> bool:
    """Verify LemonSqueezy webhook HMAC-SHA256 signature"""
    if not secret or not signature:
        return False
    try:
        expected = hmac.new(
            secret.encode(),
            body,
            hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected, signature)
    except Exception:
        return False


def process_webhook_event(payload: dict) -> None:
    """Process webhook event — separated for testability"""
    billing.process_event(payload)


def create_checkout_url(package: str, tenant_id: str = "", email: str = "") -> str:
    """Create LemonSqueezy checkout URL — separated for testability"""
    return billing.create_checkout_url(package, tenant_id, email)


def get_tenant_from_request(request: Request) -> Optional[dict]:
    """Extract tenant from API key header — separated for testability"""
    api_key = request.headers.get("X-API-Key", "")
    from api.middleware.credit_gate import get_tenant_from_api_key
    return get_tenant_from_api_key(api_key)


# ─────────────────────────────────────────────
# ROUTES
# ─────────────────────────────────────────────

@router.post("/billing/webhook", status_code=200)
async def lemonsqueezy_webhook(
    request: Request,
    x_signature: Optional[str] = Header(None, alias="X-Signature"),
) -> dict:
    """
    Receive LemonSqueezy webhook events.

    Events handled:
      subscription_created  → activate plan + set credits
      subscription_updated  → update plan
      subscription_cancelled → downgrade to free
      order_created          → topup credits

    Signature verified with HMAC-SHA256.
    Returns 403 on invalid signature.
    """
    body = await request.body()

    # Verify signature
    if not x_signature or not _verify_lemonsqueezy_signature(
        body, x_signature, WEBHOOK_SECRET
    ):
        logger.warning(
            f"Invalid webhook signature | "
            f"sig={x_signature[:20] if x_signature else 'missing'}..."
        )
        raise HTTPException(
            status_code=403,
            detail="Invalid webhook signature"
        )

    try:
        payload  = json.loads(body)
        event    = payload.get("meta", {}).get("event_name", "unknown")
        sub_id   = payload.get("data", {}).get("id", "")
        tenant_id= payload.get("meta", {}).get("custom_data", {}).get("tenant_id", "")
        logger.info(f"Webhook received: {event}")

        # Idempotency check
        if sub_id:
            tx_log = get_transaction_log()
            if tx_log.is_duplicate("lemonsqueezy", sub_id):
                logger.info(f"Duplicate LemonSqueezy webhook — skipping: {sub_id}")
                return {"ok": True, "event": event, "duplicate": True}

        process_webhook_event(payload)

        # Record transaction
        if sub_id and tenant_id:
            tx_log = get_transaction_log()
            try:
                tx_log.record({
                    "provider":       "lemonsqueezy",
                    "provider_tx_id": sub_id,
                    "tenant_id":      tenant_id,
                    "event_type":     event,
                    "status":         "processed",
                })
            except Exception as te:
                logger.warning(f"Could not record transaction: {te}")

        return {"ok": True, "event": event}

    except json.JSONDecodeError:
        logger.error("Webhook body is not valid JSON")
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    except Exception as e:
        logger.error(f"Webhook processing error: {e}")
        # Return 200 to prevent LemonSqueezy retries on our errors
        return {"ok": False, "error": str(e)}


@router.post("/billing/topup", response_model=TopupResponse)
async def topup_credits(
    request_body: TopupRequest,
    request: Request,
) -> TopupResponse:
    """
    Generate a LemonSqueezy checkout URL for purchasing more credits.

    Packages:
      credits_50:  50 credits for $45 ($0.90/video)
      credits_100: 100 credits for $80 ($0.80/video — best rate)

    Returns a checkout URL to redirect the user to LemonSqueezy.
    """
    if request_body.package not in TOPUP_PACKAGES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid package '{request_body.package}'. "
                   f"Valid options: {list(TOPUP_PACKAGES.keys())}"
        )

    tenant  = get_tenant_from_request(request)
    pkg     = TOPUP_PACKAGES[request_body.package]

    tenant_id = tenant["id"] if tenant else ""
    email     = tenant.get("email", "") if tenant else ""

    url = create_checkout_url(
        package=request_body.package,
        tenant_id=tenant_id,
        email=email,
    )

    return TopupResponse(
        checkout_url=  url,
        package=       request_body.package,
        credits=       pkg["credits"],
        price_dollars= pkg["price_cents"] / 100,
    )


@router.get("/billing/balance", response_model=BalanceResponse)
async def get_balance(request: Request) -> BalanceResponse:
    """
    Get current credit balance and plan for the authenticated tenant.
    """
    tenant = get_tenant_from_request(request)

    if not tenant:
        raise HTTPException(
            status_code=401,
            detail="API key required. Set X-API-Key header."
        )

    plan        = tenant.get("plan", "free")
    credits     = int(tenant.get("credits", 0))
    plan_config = billing.get_plan_config(plan)

    plan_names = {
        "free":    "Free",
        "starter": "Starter",
        "pro":     "Pro",
        "agency":  "Agency",
    }

    return BalanceResponse(
        credits=       credits,
        plan=          plan,
        plan_name=     plan_names.get(plan, plan.title()),
        monthly_alloc= plan_config["monthly_credits"],
    )


@router.get("/billing/plans")
async def list_plans() -> list:
    """
    List all available HezCast plans with pricing and features.
    Public endpoint — no auth required.
    """
    from core.billing import PLAN_CONFIG
    plans = []
    for plan_id, config in PLAN_CONFIG.items():
        plans.append({
            "id":              plan_id,
            "name":            plan_id.title(),
            "price_monthly":   config["price_monthly"],
            "price_annual":    config["price_annual"],
            "monthly_credits": config["monthly_credits"],
            "max_brands":      config["max_brands"],
            "has_avatar":      config["has_avatar"],
            "has_api":         config["has_api"],
            "rollover_days":   config["rollover_days"],
        })
    return plans
