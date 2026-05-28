"""HezCast Engine — Health Route"""

import os
from fastapi import APIRouter
from api.schemas import HealthResponse

router = APIRouter(tags=["System"])

VERSION = "2.0.0"

@router.get("/health", response_model=HealthResponse)
def health_check():
    """System health check — reports API, Redis, and worker states"""
    services = {
        "api":    "online",
        "redis":  _check_redis(),
        "worker": "unknown",
    }
    return HealthResponse(
        status="ok",
        version=VERSION,
        services=services,
    )

def _check_redis() -> str:
    try:
        import redis
        r = redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"))
        r.ping()
        return "online"
    except Exception:
        return "offline"
