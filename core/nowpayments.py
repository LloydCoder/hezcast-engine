"""
HezCast Engine — NOWPayments Integration
Tinlance Limited | Apache 2.0

Handles crypto payments alongside LemonSqueezy.
Stablecoins only — no volatile crypto (BTC/ETH).

Supported currencies:
  USDT TRC-20 (Tron)    — lowest fees ~$1
  USDT ERC-20 (Ethereum) — widely held
  USDT BEP-20 (BSC)     — low fees
  USDC ERC-20           — Circle-backed
  USDC BEP-20           — Circle-backed
  DAI  ERC-20           — Decentralized stable

Payment flow:
  1. User clicks "Pay with Crypto"
  2. create_invoice() → returns nowpayments.io checkout URL
  3. User pays on-chain
  4. NOWPayments calls POST /billing/nowpayments/webhook (IPN)
  5. process_payment() → activates plan or adds credits
  6. Same DB update as LemonSqueezy

Order ID format:
  topup_credits50_<tenant_id>    → add 50 credits
  topup_credits100_<tenant_id>   → add 100 credits
  plan_starter_<tenant_id>       → activate starter plan
  plan_pro_<tenant_id>           → activate pro plan
  plan_agency_<tenant_id>        → activate agency plan

Setup:
  1. Create account at nowpayments.io
  2. Get API key from dashboard
  3. Set IPN callback URL: https://api.hezcast.com/billing/nowpayments/webhook
  4. Get IPN secret from dashboard
  5. Add to .env:
     NOWPAYMENTS_API_KEY=your_api_key
     NOWPAYMENTS_IPN_SECRET=your_ipn_secret
"""

import hashlib
import hmac
import json
import logging
import os
import requests
from typing import Optional

logger = logging.getLogger(__name__)

# NOWPayments API base
NOWPAYMENTS_API = "https://api.nowpayments.io/v1"

# Stablecoins only — no volatile crypto
SUPPORTED_CURRENCIES = [
    {
        "id":      "usdttrc20",
        "name":    "USDT (TRC-20 / Tron)",
        "symbol":  "USDT",
        "network": "TRC-20",
        "fees":    "~$1",
        "recommended": True,
    },
    {
        "id":      "usdterc20",
        "name":    "USDT (ERC-20 / Ethereum)",
        "symbol":  "USDT",
        "network": "ERC-20",
        "fees":    "~$5-20",
        "recommended": False,
    },
    {
        "id":      "usdtbsc",
        "name":    "USDT (BEP-20 / BSC)",
        "symbol":  "USDT",
        "network": "BEP-20",
        "fees":    "~$0.50",
        "recommended": False,
    },
    {
        "id":      "usdcerc20",
        "name":    "USDC (ERC-20 / Ethereum)",
        "symbol":  "USDC",
        "network": "ERC-20",
        "fees":    "~$5-20",
        "recommended": False,
    },
    {
        "id":      "usdcbsc",
        "name":    "USDC (BEP-20 / BSC)",
        "symbol":  "USDC",
        "network": "BEP-20",
        "fees":    "~$0.50",
        "recommended": False,
    },
    {
        "id":      "daierc20",
        "name":    "DAI (ERC-20 / Ethereum)",
        "symbol":  "DAI",
        "network": "ERC-20",
        "fees":    "~$5-20",
        "recommended": False,
    },
]

# Confirmed payment statuses
CONFIRMED_STATUSES = {"confirmed", "finished"}

# Plan prices in USD
PLAN_PRICES = {
    "starter": 19.00,
    "pro":     49.00,
    "agency":  149.00,
}

# Topup package prices
TOPUP_PRICES = {
    "credits_50":  45.00,
    "credits_100": 80.00,
}


class NOWPaymentsManager:
    """
    Manages crypto payments via NOWPayments API.

    Usage:
        mgr = NOWPaymentsManager()

        # Create invoice
        invoice = mgr.create_invoice(
            amount=49.00,
            currency="usd",
            order_id=mgr.build_order_id("plan", plan="pro", tenant_id="t001"),
            description="HezCast Pro Plan",
        )
        # → redirect user to invoice["invoice_url"]

        # Process IPN webhook
        if mgr.verify_ipn_signature(payload, sig, secret):
            mgr.process_payment(payload, billing_manager)
    """

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("NOWPAYMENTS_API_KEY", "")
        if not self.api_key:
            raise ValueError(
                "api_key not provided and NOWPAYMENTS_API_KEY env var not set"
            )

    # ─────────────────────────────────────────
    # CURRENCIES
    # ─────────────────────────────────────────

    def get_supported_currencies(self) -> list:
        """Return list of supported stablecoin currencies"""
        return SUPPORTED_CURRENCIES.copy()

    def is_stablecoin(self, currency_id: str) -> bool:
        """Return True if currency is an approved stablecoin"""
        supported_ids = {c["id"] for c in SUPPORTED_CURRENCIES}
        return currency_id.lower() in supported_ids

    # ─────────────────────────────────────────
    # INVOICE CREATION
    # ─────────────────────────────────────────

    def create_invoice(
        self,
        amount:      float,
        currency:    str,
        order_id:    str,
        description: str,
        pay_currency: str = "usdttrc20",
        ipn_callback_url: Optional[str] = None,
    ) -> dict:
        """
        Create a NOWPayments invoice and return checkout URL.

        Args:
            amount:      Price in fiat (USD)
            currency:    Fiat currency code (must be 'usd')
            order_id:    Internal order ID for webhook correlation
            description: Human-readable payment description
            pay_currency: Crypto to accept (default: USDT TRC-20)
            ipn_callback_url: Where NOWPayments sends IPN notifications

        Returns:
            dict with invoice_url, payment_id, pay_address, etc.

        Raises:
            ValueError: If amount <= 0 or currency not USD
            NOWPaymentsError: If API call fails
        """
        if amount <= 0:
            raise ValueError(f"amount must be positive (got {amount})")

        if currency.lower() not in ("usd", "usdt", "usdc"):
            raise ValueError(
                f"currency must be 'usd' (got '{currency}'). "
                f"HezCast prices are in USD."
            )

        callback_url = ipn_callback_url or os.getenv(
            "NOWPAYMENTS_IPN_URL",
            "https://api.hezcast.com/billing/nowpayments/webhook"
        )

        payload = {
            "price_amount":      amount,
            "price_currency":    "usd",
            "pay_currency":      pay_currency.lower(),
            "order_id":          order_id,
            "order_description": description,
            "ipn_callback_url":  callback_url,
            "is_fixed_rate":     True,
            "is_fee_paid_by_user": False,
        }

        logger.info(
            f"Creating NOWPayments invoice | "
            f"amount=${amount} | order={order_id} | currency={pay_currency}"
        )

        response = self._api_request("POST", "/invoice", json=payload)

        logger.info(
            f"Invoice created | "
            f"id={response.get('id')} | "
            f"url={response.get('invoice_url', '')[:50]}"
        )

        return response

    # ─────────────────────────────────────────
    # ORDER ID MANAGEMENT
    # ─────────────────────────────────────────

    def build_order_id(
        self,
        type:      str,
        tenant_id: str,
        plan:      Optional[str] = None,
        package:   Optional[str] = None,
    ) -> str:
        """
        Build a structured order ID for webhook correlation.

        Formats:
          plan_pro_tenant001
          plan_starter_tenant001
          topup_credits50_tenant001
          topup_credits100_tenant001
        """
        if type == "plan" and plan:
            return f"plan_{plan}_{tenant_id}"
        elif type == "topup" and package:
            pkg_clean = package.replace("credits_", "credits")
            return f"topup_{pkg_clean}_{tenant_id}"
        else:
            raise ValueError(
                f"Cannot build order_id: type={type}, plan={plan}, package={package}"
            )

    def parse_order_id(self, order_id: str) -> dict:
        """
        Parse a structured order ID back into components.

        Args:
            order_id: e.g. "plan_pro_tenant001" or "topup_credits50_tenant001"

        Returns:
            dict with type, tenant_id, and plan or package

        Raises:
            ValueError: If order_id format is invalid
        """
        parts = order_id.split("_", 2)

        if len(parts) < 3:
            raise ValueError(
                f"Invalid order_id format: '{order_id}'. "
                f"Expected: plan_<plan>_<tenant_id> or topup_<package>_<tenant_id>"
            )

        order_type = parts[0]
        detail     = parts[1]
        tenant_id  = parts[2]

        if order_type == "plan":
            return {
                "type":      "plan",
                "plan":      detail,
                "tenant_id": tenant_id,
            }
        elif order_type == "topup":
            return {
                "type":      "topup",
                "package":   f"credits_{detail.replace('credits', '')}",
                "tenant_id": tenant_id,
            }
        else:
            raise ValueError(
                f"Unknown order type: '{order_type}'. Expected 'plan' or 'topup'."
            )

    # ─────────────────────────────────────────
    # IPN SIGNATURE VERIFICATION
    # ─────────────────────────────────────────

    def verify_ipn_signature(
        self,
        payload:   dict,
        signature: str,
        secret:    str,
    ) -> bool:
        """
        Verify NOWPayments IPN HMAC-SHA512 signature.

        NOWPayments signs the JSON payload sorted by keys.

        Args:
            payload:   Parsed IPN payload dict
            signature: x-nowpayments-sig header value
            secret:    IPN secret from NOWPayments dashboard

        Returns:
            True if signature is valid, False otherwise
        """
        if not signature or not secret:
            return False

        try:
            sorted_body = json.dumps(
                payload,
                sort_keys=True,
                separators=(',', ':')
            )
            expected = hmac.new(
                secret.encode(),
                sorted_body.encode(),
                hashlib.sha512
            ).hexdigest()
            return hmac.compare_digest(expected, signature)
        except Exception as e:
            logger.warning(f"IPN signature verification failed: {e}")
            return False

    # ─────────────────────────────────────────
    # PAYMENT PROCESSING
    # ─────────────────────────────────────────

    def is_payment_confirmed(self, payload: dict) -> bool:
        """Return True if payment status is confirmed or finished"""
        return payload.get("payment_status", "").lower() in CONFIRMED_STATUSES

    def process_payment(self, payload: dict, billing) -> None:
        """
        Process a confirmed NOWPayments IPN event.

        For 'waiting', 'partially_paid', 'expired', 'failed' — do nothing.
        For 'confirmed', 'finished' — activate plan or add credits.

        Args:
            payload: IPN payload dict
            billing: BillingManager instance
        """
        status   = payload.get("payment_status", "").lower()
        order_id = payload.get("order_id", "")

        logger.info(
            f"NOWPayments IPN | status={status} | order={order_id}"
        )

        # Only process confirmed payments
        if status not in CONFIRMED_STATUSES:
            logger.debug(f"Ignoring non-confirmed payment: {status}")
            return

        if not order_id:
            logger.warning("IPN received with no order_id — ignoring")
            return

        try:
            parsed = self.parse_order_id(order_id)
        except ValueError as e:
            logger.error(f"Could not parse order_id '{order_id}': {e}")
            return

        tenant_id = parsed["tenant_id"]

        if parsed["type"] == "plan":
            plan = parsed["plan"]
            billing.activate_plan(tenant_id, plan)
            logger.info(
                f"Plan activated via crypto | "
                f"tenant={tenant_id[:8]} | plan={plan}"
            )

        elif parsed["type"] == "topup":
            # Determine credits from price amount
            price = float(payload.get("price_amount", 0))
            if price >= 80:
                credits = 100
            elif price >= 45:
                credits = 50
            else:
                # Fallback: infer from package string
                pkg = parsed.get("package", "credits_50")
                credits = 100 if "100" in pkg else 50

            billing.add_credits(tenant_id, credits)
            logger.info(
                f"Credits added via crypto | "
                f"tenant={tenant_id[:8]} | credits={credits}"
            )

    # ─────────────────────────────────────────
    # API CLIENT (mockable in tests)
    # ─────────────────────────────────────────

    def _api_request(
        self,
        method: str,
        path:   str,
        json:   Optional[dict] = None,
    ) -> dict:
        """
        Make request to NOWPayments API.
        In tests: mocked via patch.object(mgr, '_api_request').
        """
        url = f"{NOWPAYMENTS_API}{path}"
        headers = {
            "x-api-key":   self.api_key,
            "Content-Type": "application/json",
        }

        try:
            resp = requests.request(
                method, url,
                headers=headers,
                json=json,
                timeout=30,
            )
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.HTTPError as e:
            raise NOWPaymentsError(f"NOWPayments API error: {e}")
        except requests.exceptions.Timeout:
            raise NOWPaymentsError("NOWPayments API request timed out")
        except requests.exceptions.ConnectionError as e:
            raise NOWPaymentsError(f"NOWPayments API connection error: {e}")


# ─────────────────────────────────────────────
# EXCEPTIONS
# ─────────────────────────────────────────────

class NOWPaymentsError(Exception):
    """Raised when NOWPayments API call fails"""
    pass
