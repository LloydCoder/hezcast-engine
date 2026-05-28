"""
HezCast Engine — FastAPI Application
Tinlance Limited | Apache 2.0
"""

import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import generate, status, hooks, health, brands, telegram_webhook, billing, onboarding, nowpayments, jobs

logger = logging.getLogger(__name__)

VERSION = "2.0.0"


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"HezCast Engine v{VERSION} starting...")
    yield
    logger.info("HezCast Engine shutting down.")


app = FastAPI(
    title="HezCast Engine",
    description="Open-core AI content broadcasting system by Tinlance Limited",
    version=VERSION,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(brands.router)
app.include_router(generate.router)
app.include_router(status.router)
app.include_router(hooks.router)
app.include_router(telegram_webhook.router)
app.include_router(billing.router)
app.include_router(onboarding.router)
app.include_router(nowpayments.router)
app.include_router(jobs.router)
