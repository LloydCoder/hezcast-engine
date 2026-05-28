"""
HezCast Engine — Credit Gate Middleware
Tinlance Limited | Apache 2.0

FastAPI middleware that checks tenant credit balance
before allowing POST /generate requests.

Flow:
  POST /generate
       ↓
  Extract API key from X-API-Key header
       ↓
  get_tenant_credits(api_key) → int
       ↓
  credits > 0? → allow request → pipeline runs → deduct 1 credit
  credits == 0? → 402 Payment Required → helpful upgrade message

The credit deduction happens AFTER successful QA pass,
not at job submission time. Failed renders do not cost credits.
"""

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

# In-memory tenant store (shared with generate route)
# In production: queries PostgreSQL
_tenant_credit_cache: dict = {}


def get_tenant_credits(api_key: str) -> int:
    """
    Get credit balance for a tenant by API key.

    In production: queries PostgreSQL tenants table.
    In tests: mocked via patch.

    Returns:
        Credit balance (int). Returns 999 if no API key
        provided (development/open mode).
    """
    if not api_key:
        # No API key = development mode = unlimited
        return 999

    # Check cache first
    if api_key in _tenant_credit_cache:
        return _tenant_credit_cache[api_key]

    # In production: query DB
    # For now: return 999 for known test keys
    if api_key.startswith("test_key"):
        return 999

    return 999  # Default open access until auth is wired


def get_tenant_from_api_key(api_key: str) -> Optional[dict]:
    """
    Get full tenant record by API key.

    In production: queries PostgreSQL tenants table.
    In tests: mocked.
    """
    if not api_key:
        return {
            "id":      "dev",
            "plan":    "pro",
            "credits": 999,
            "email":   "dev@localhost",
        }

    # Known test keys
    if api_key.startswith("test_key"):
        return {
            "id":      f"tenant_{api_key[-6:]}",
            "plan":    "starter",
            "credits": _tenant_credit_cache.get(api_key, 15),
            "email":   "test@example.com",
        }

    return None
