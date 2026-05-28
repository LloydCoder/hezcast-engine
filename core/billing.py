"""
HezCast Engine — Billing Manager
Tinlance Limited | Apache 2.0

Handles:
  - Plan configuration (free/starter/pro/agency)
  - Credit management (deduct, add, balance)
  - Plan activation/cancellation
  - LemonSqueezy webhook event processing

In production: reads/writes from PostgreSQL tenants table
In tests: _get_tenant and _save_tenant are mocked
"""

import json
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# PLAN CONFIGURATION
# ─────────────────────────────────────────────

PLAN_CONFIG = {
    "free": {
        "monthly_credits":       3,
        "price_monthly":         0,
        "price_annual":          0,
        "max_brands":            1,
        "hook_variants":         3,
        "max_telegram_channels": 1,
        "video_retention_days":  1,
        "archive_retention_days": 0,
        "has_avatar":            False,
        "has_watermark":         True,
        "has_api":               False,
        "api_calls_monthly":     0,
        "credit_topup_rate":     None,
        "rollover_days":         0,
    },
    "starter": {
        "monthly_credits":       15,
        "price_monthly":         19,
        "price_annual":          190,
        "max_brands":            1,
        "hook_variants":         5,
        "max_telegram_channels": 1,
        "video_retention_days":  7,
        "archive_retention_days": 30,
        "has_avatar":            True,
        "has_watermark":         False,
        "has_api":               False,
        "api_calls_monthly":     0,
        "credit_topup_rate":     1.50,
        "rollover_days":         30,
    },
    "pro": {
        "monthly_credits":       60,
        "price_monthly":         49,
        "price_annual":          490,
        "max_brands":            5,
        "hook_variants":         5,
        "max_telegram_channels": 3,
        "video_retention_days":  7,
        "archive_retention_days": 90,
        "has_avatar":            True,
        "has_watermark":         False,
        "has_api":               True,
        "api_calls_monthly":     1000,
        "credit_topup_rate":     1.00,
        "rollover_days":         60,
    },
    "agency": {
        "monthly_credits":       300,
        "price_monthly":         149,
        "price_annual":          1490,
        "max_brands":            -1,    # unlimited
        "hook_variants":         5,
        "max_telegram_channels": -1,    # unlimited
        "video_retention_days":  7,
        "archive_retention_days": 180,
        "has_avatar":            True,
        "has_watermark":         False,
        "has_api":               True,
        "api_calls_monthly":     -1,    # unlimited
        "credit_topup_rate":     0.60,
        "rollover_days":         -1,    # never expire
    },
}

# LemonSqueezy product name → plan mapping
PRODUCT_PLAN_MAP = {
    "hezcast starter":       "starter",
    "hezcast pro":           "pro",
    "hezcast agency":        "agency",
    "starter":               "starter",
    "pro":                   "pro",
    "agency":                "agency",
    "hezcast starter monthly": "starter",
    "hezcast pro monthly":     "pro",
    "hezcast agency monthly":  "agency",
    "hezcast starter annual":  "starter",
    "hezcast pro annual":      "pro",
    "hezcast agency annual":   "agency",
}

# Topup package definitions
TOPUP_PACKAGES = {
    "credits_50":  {"credits": 50,  "price_cents": 4500},
    "credits_100": {"credits": 100, "price_cents": 8000},
}


class BillingManager:
    """
    Manages HezCast subscription plans and credit system.

    Usage:
        billing = BillingManager()

        # Check credits
        if billing.has_credits(tenant_id):
            billing.deduct_credit(tenant_id)

        # Process LemonSqueezy event
        billing.process_event(webhook_payload)

        # Activate plan
        billing.activate_plan(tenant_id, "pro")
    """

    # In-memory tenant store (replaced by DB in production)
    _tenants: dict = {}

    def __init__(self):
        # Import shared job store from API layer
        try:
            from api.routes.generate import _jobs
            self._jobs = _jobs
        except ImportError:
            self._jobs = {}

    # ─────────────────────────────────────────
    # PLAN CONFIGURATION
    # ─────────────────────────────────────────

    def get_plan_config(self, plan: str) -> dict:
        """
        Get configuration for a plan.

        Raises:
            ValueError: If plan is unknown
        """
        if plan not in PLAN_CONFIG:
            available = list(PLAN_CONFIG.keys())
            raise ValueError(
                f"Unknown plan: '{plan}'. Available: {available}"
            )
        return PLAN_CONFIG[plan].copy()

    # ─────────────────────────────────────────
    # CREDIT MANAGEMENT
    # ─────────────────────────────────────────

    def has_credits(self, tenant_id: str) -> bool:
        """Return True if tenant has at least 1 credit"""
        tenant = self._get_tenant(tenant_id)
        return tenant.get("credits", 0) > 0

    def get_balance(self, tenant_id: str) -> int:
        """Return current credit balance"""
        tenant = self._get_tenant(tenant_id)
        return int(tenant.get("credits", 0))

    def deduct_credit(self, tenant_id: str) -> int:
        """
        Deduct 1 credit from tenant balance.

        Returns:
            New credit balance (int)

        Raises:
            InsufficientCreditsError: If balance is 0
        """
        tenant = self._get_tenant(tenant_id)
        current = int(tenant.get("credits", 0))

        if current <= 0:
            raise InsufficientCreditsError(
                f"No credits remaining. "
                f"Upgrade your plan or topup at cast.tinlance.com/billing"
            )

        tenant["credits"] = current - 1
        self._save_tenant(tenant)

        logger.info(
            f"Credit deducted | tenant={tenant_id[:8]} | "
            f"balance={tenant['credits']}"
        )
        return tenant["credits"]

    def add_credits(self, tenant_id: str, amount: int) -> int:
        """
        Add credits to tenant balance.

        Args:
            tenant_id: Tenant ID
            amount:    Number of credits to add (must be > 0)

        Returns:
            New credit balance (int)

        Raises:
            ValueError: If amount <= 0
        """
        if amount <= 0:
            raise ValueError(
                f"amount must be a positive integer (got {amount})"
            )

        tenant = self._get_tenant(tenant_id)
        current = int(tenant.get("credits", 0))
        tenant["credits"] = current + amount
        self._save_tenant(tenant)

        logger.info(
            f"Credits added | tenant={tenant_id[:8]} | "
            f"added={amount} | balance={tenant['credits']}"
        )
        return tenant["credits"]

    # ─────────────────────────────────────────
    # PLAN MANAGEMENT
    # ─────────────────────────────────────────

    def activate_plan(
        self,
        tenant_id: str,
        plan: str,
        preserve_credits: bool = False
    ) -> dict:
        """
        Activate a subscription plan for a tenant.

        Args:
            tenant_id:        Tenant ID
            plan:             Plan name (starter/pro/agency)
            preserve_credits: If True, keep existing credits (upgrade path)

        Returns:
            Updated tenant dict
        """
        config = self.get_plan_config(plan)
        tenant = self._get_tenant(tenant_id)

        old_plan = tenant.get("plan", "free")
        tenant["plan"] = plan

        if preserve_credits:
            # Upgrade: keep existing credits
            existing = int(tenant.get("credits", 0))
            tenant["credits"] = max(existing, config["monthly_credits"])
        else:
            # Fresh activation: set to plan's monthly allocation
            tenant["credits"] = config["monthly_credits"]

        self._save_tenant(tenant)

        logger.info(
            f"Plan activated | tenant={tenant_id[:8]} | "
            f"{old_plan} → {plan} | credits={tenant['credits']}"
        )
        return tenant

    def cancel_plan(self, tenant_id: str) -> dict:
        """
        Cancel subscription and downgrade to free plan.

        Args:
            tenant_id: Tenant ID

        Returns:
            Updated tenant dict (free plan, 3 credits)
        """
        free_config = self.get_plan_config("free")
        tenant = self._get_tenant(tenant_id)

        old_plan = tenant.get("plan", "free")
        tenant["plan"]    = "free"
        tenant["credits"] = free_config["monthly_credits"]

        self._save_tenant(tenant)

        logger.info(
            f"Plan cancelled | tenant={tenant_id[:8]} | "
            f"{old_plan} → free"
        )
        return tenant

    # ─────────────────────────────────────────
    # LEMONSQUEEZY EVENT PROCESSOR
    # ─────────────────────────────────────────

    def process_event(self, payload: dict) -> None:
        """
        Process a LemonSqueezy webhook event.

        Supported events:
          subscription_created  → activate plan
          subscription_updated  → update plan
          subscription_cancelled → cancel plan
          order_created         → topup credits

        Args:
            payload: Parsed JSON webhook payload
        """
        meta       = payload.get("meta", {})
        event_name = meta.get("event_name", "")
        custom     = meta.get("custom_data", {})
        data       = payload.get("data", {})
        attributes = data.get("attributes", {})
        tenant_id  = custom.get("tenant_id", "")

        logger.info(f"Processing webhook event: {event_name}")

        if event_name in ("subscription_created", "subscription_updated"):
            self._handle_subscription_created(tenant_id, attributes)

        elif event_name == "subscription_cancelled":
            if tenant_id:
                self.cancel_plan(tenant_id)

        elif event_name == "order_created":
            self._handle_order_created(tenant_id, custom, attributes)

        else:
            logger.debug(f"Unhandled webhook event: {event_name}")

    def _handle_subscription_created(
        self, tenant_id: str, attributes: dict
    ) -> None:
        """Map LemonSqueezy product name to HezCast plan and activate"""
        if not tenant_id:
            logger.warning("subscription_created with no tenant_id")
            return

        product_name = attributes.get("product_name", "").lower().strip()
        plan = PRODUCT_PLAN_MAP.get(product_name)

        if not plan:
            # Try partial match
            for key, mapped_plan in PRODUCT_PLAN_MAP.items():
                if key in product_name or product_name in key:
                    plan = mapped_plan
                    break

        if not plan:
            logger.warning(
                f"Could not map product '{product_name}' to a plan. "
                f"Defaulting to starter."
            )
            plan = "starter"

        self.activate_plan(tenant_id, plan)

    def _handle_order_created(
        self,
        tenant_id: str,
        custom: dict,
        attributes: dict
    ) -> None:
        """Add topup credits on order completion"""
        if not tenant_id:
            logger.warning("order_created with no tenant_id")
            return

        status = attributes.get("status", "")
        if status != "paid":
            logger.debug(f"Order not paid (status={status}) — skipping")
            return

        # Credit amount from custom_data or package lookup
        credit_amount = custom.get("credit_amount")
        if not credit_amount:
            # Try to infer from order amount
            total_cents = attributes.get("total", 0)
            if total_cents == 4500:
                credit_amount = 50
            elif total_cents == 8000:
                credit_amount = 100
            else:
                credit_amount = 50  # safe default

        self.add_credits(tenant_id, int(credit_amount))

    # ─────────────────────────────────────────
    # LEMONSQUEEZY CHECKOUT
    # ─────────────────────────────────────────

    def create_checkout_url(
        self,
        package: str,
        tenant_id: str,
        tenant_email: str = ""
    ) -> str:
        """
        Generate a LemonSqueezy checkout URL for a credit topup.

        Args:
            package:      'credits_50' or 'credits_100'
            tenant_id:    For webhook custom_data
            tenant_email: Pre-fill email in checkout

        Returns:
            Checkout URL (str)
        """
        if package not in TOPUP_PACKAGES:
            raise ValueError(
                f"Unknown topup package: '{package}'. "
                f"Available: {list(TOPUP_PACKAGES.keys())}"
            )

        # LemonSqueezy checkout URL structure
        store_slug   = os.getenv("LEMONSQUEEZY_STORE_SLUG", "hezcast")
        variant_ids  = {
            "credits_50":  os.getenv("LS_VARIANT_CREDITS_50",  "credits50"),
            "credits_100": os.getenv("LS_VARIANT_CREDITS_100", "credits100"),
        }
        variant_id = variant_ids[package]

        url = (
            f"https://{store_slug}.lemonsqueezy.com/checkout/buy/{variant_id}"
            f"?checkout[custom][tenant_id]={tenant_id}"
            f"&checkout[custom][credit_amount]={TOPUP_PACKAGES[package]['credits']}"
        )

        if tenant_email:
            url += f"&checkout[email]={tenant_email}"

        return url

    # ─────────────────────────────────────────
    # TENANT STORE (mockable in tests)
    # ─────────────────────────────────────────

    def _get_tenant(self, tenant_id: str) -> dict:
        """
        Get tenant by ID from store.
        In production: queries PostgreSQL tenants table.
        In tests: mocked via patch.
        """
        return self._tenants.get(
            tenant_id,
            {"id": tenant_id, "credits": 0, "plan": "free"}
        )

    def _get_tenant_by_id(self, tenant_id: str) -> Optional[dict]:
        """Alias for _get_tenant — used in event processing"""
        return self._get_tenant(tenant_id)

    def _save_tenant(self, tenant: dict) -> None:
        """
        Save tenant to store.
        In production: updates PostgreSQL tenants table.
        In tests: mocked via patch.
        """
        if "id" in tenant:
            self._tenants[tenant["id"]] = tenant


# ─────────────────────────────────────────────
# EXCEPTIONS
# ─────────────────────────────────────────────

class InsufficientCreditsError(Exception):
    """Raised when tenant has no credits remaining"""
    pass


class BillingError(Exception):
    """Raised on billing system failures"""
    pass
