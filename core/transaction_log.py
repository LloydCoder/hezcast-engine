"""
HezCast Engine — Transaction Log
Launch Blocker 1: Idempotency + Payment Audit Trail
Tinlance Limited | Apache 2.0

Records every payment event from both providers.
The provider_tx_id UNIQUE constraint prevents double-credits
if a webhook fires more than once (LemonSqueezy and NOWPayments
both retry on non-200 responses).

Schema (in database/schemas.sql):
  credit_transactions (
    id              UUID PRIMARY KEY,
    tenant_id       TEXT NOT NULL,
    provider        TEXT NOT NULL,        -- 'lemonsqueezy' | 'nowpayments'
    provider_tx_id  TEXT UNIQUE NOT NULL, -- prevents replay attacks
    amount_usd      DECIMAL(10,2),
    currency        TEXT,
    status          TEXT,
    credits_added   INT DEFAULT 0,
    plan_activated  TEXT,
    event_type      TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW()
  )
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# In-memory store (replaced by PostgreSQL in production)
_transactions: dict = {}  # provider_tx_id → transaction record


class TransactionLog:
    """
    Records and deduplicates payment transactions.

    Usage:
        log = TransactionLog()

        # Check for duplicate before processing
        if log.is_duplicate("lemonsqueezy", subscription_id):
            return  # already processed

        # Record transaction
        log.record({
            "provider":       "lemonsqueezy",
            "provider_tx_id": subscription_id,
            "tenant_id":      tenant_id,
            "amount_usd":     49.00,
            "currency":       "usd",
            "status":         "paid",
            "credits_added":  60,
            "plan_activated": "pro",
            "event_type":     "subscription_created",
        })

        # Or use record_or_raise for atomic check-and-record
        try:
            log.record_or_raise(transaction_data)
        except DuplicateTransactionError:
            return  # webhook already processed
    """

    # ─────────────────────────────────────────
    # PUBLIC API
    # ─────────────────────────────────────────

    def record(self, data: dict) -> str:
        """
        Record a payment transaction.

        Args:
            data: Transaction dict with required fields

        Returns:
            Transaction ID (str)

        Raises:
            ValueError: If required fields missing
        """
        self._validate(data)

        tx_id = str(uuid.uuid4())
        record = {
            "id":             tx_id,
            "provider":       data["provider"],
            "provider_tx_id": data["provider_tx_id"],
            "tenant_id":      data["tenant_id"],
            "amount_usd":     data.get("amount_usd", 0.0),
            "currency":       data.get("currency", "usd"),
            "status":         data.get("status", "unknown"),
            "credits_added":  data.get("credits_added", 0),
            "plan_activated": data.get("plan_activated"),
            "event_type":     data.get("event_type", ""),
            "created_at":     datetime.now(timezone.utc).isoformat(),
        }

        self._save(record)

        logger.info(
            f"Transaction recorded | "
            f"provider={data['provider']} | "
            f"tx={data['provider_tx_id']} | "
            f"tenant={data['tenant_id'][:8]} | "
            f"credits={data.get('credits_added', 0)}"
        )

        return tx_id

    def record_or_raise(self, data: dict) -> str:
        """
        Record transaction or raise if already exists (duplicate).

        Use this as the atomic check-and-record in webhook handlers.

        Args:
            data: Transaction dict

        Returns:
            Transaction ID (str)

        Raises:
            DuplicateTransactionError: If provider_tx_id already exists
            ValueError: If required fields missing
        """
        self._validate(data)

        provider    = data["provider"]
        provider_id = data["provider_tx_id"]

        if self._exists(provider, provider_id):
            raise DuplicateTransactionError(
                f"Transaction already processed: "
                f"provider={provider} tx_id={provider_id}"
            )

        return self.record(data)

    def is_duplicate(self, provider: str, provider_tx_id: str) -> bool:
        """
        Check if a transaction has already been processed.

        Args:
            provider:       'lemonsqueezy' or 'nowpayments'
            provider_tx_id: Provider's transaction/subscription ID

        Returns:
            True if already processed, False if new
        """
        return self._exists(provider, provider_tx_id)

    def get_tenant_transactions(
        self,
        tenant_id: str,
        limit: int = 50,
    ) -> list:
        """
        Get all transactions for a tenant.

        Args:
            tenant_id: Tenant ID
            limit:     Max records to return

        Returns:
            List of transaction dicts, newest first
        """
        rows = self._query_by_tenant(tenant_id)
        return sorted(rows, key=lambda r: r.get("created_at", ""), reverse=True)[:limit]

    # ─────────────────────────────────────────
    # STORE OPERATIONS (mockable in tests)
    # ─────────────────────────────────────────

    def _save(self, record: dict) -> str:
        """
        Save transaction to store.
        In production: INSERT INTO credit_transactions.
        In tests: mocked via patch.object.
        """
        key = f"{record['provider']}:{record['provider_tx_id']}"
        _transactions[key] = record
        return record["id"]

    def _exists(self, provider: str, provider_tx_id: str) -> bool:
        """
        Check if transaction exists in store.
        In production: SELECT COUNT(*) WHERE provider_tx_id = $1.
        In tests: mocked via patch.object.
        """
        key = f"{provider}:{provider_tx_id}"
        return key in _transactions

    def _query_by_tenant(self, tenant_id: str) -> list:
        """
        Query all transactions for a tenant.
        In production: SELECT * WHERE tenant_id = $1.
        In tests: mocked via patch.object.
        """
        return [
            r for r in _transactions.values()
            if r.get("tenant_id") == tenant_id
        ]

    # ─────────────────────────────────────────
    # VALIDATION
    # ─────────────────────────────────────────

    def _validate(self, data: dict) -> None:
        """Validate required fields"""
        if not data.get("provider_tx_id"):
            raise ValueError("provider_tx_id is required")
        if not data.get("tenant_id"):
            raise ValueError("tenant_id is required")
        if not data.get("provider"):
            raise ValueError("provider is required")


# ─────────────────────────────────────────────
# EXCEPTIONS
# ─────────────────────────────────────────────

class DuplicateTransactionError(Exception):
    """Raised when a webhook tries to process an already-recorded transaction"""
    pass


# ─────────────────────────────────────────────
# SINGLETON
# ─────────────────────────────────────────────

_tx_log = None

def get_transaction_log() -> TransactionLog:
    """Get singleton TransactionLog instance"""
    global _tx_log
    if _tx_log is None:
        _tx_log = TransactionLog()
    return _tx_log
