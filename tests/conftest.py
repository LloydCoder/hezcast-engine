"""HezCast Test Configuration"""
import pytest

@pytest.fixture(autouse=True)
def clear_shared_state():
    """Clear all shared in-memory stores between tests"""
    yield
    # Clear transaction log
    try:
        from core.transaction_log import _transactions
        _transactions.clear()
    except Exception:
        pass
    # Clear jobs store
    try:
        from api.routes.generate import _jobs, _hooks_store
        _jobs.clear()
        _hooks_store.clear()
    except Exception:
        pass
    # Clear tenant store in billing
    try:
        from core.billing import BillingManager
        BillingManager._tenants.clear()
    except Exception:
        pass
