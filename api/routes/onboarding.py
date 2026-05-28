"""
HezCast Engine — Brand Onboarding Routes
Tinlance Limited | Apache 2.0

Endpoints:
  POST /onboarding/brand     ← Create brand config for new tenant
  GET  /onboarding/brands    ← List tenant's brands
  GET  /onboarding/complete  ← Check onboarding completion status
"""

import json
import logging
import re
import uuid
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from typing import Optional

from core.billing import BillingManager, PLAN_CONFIG

router  = APIRouter(tags=["Onboarding"])
logger  = logging.getLogger(__name__)
billing = BillingManager()

# In-memory brand store (DB in production)
_tenant_brands: dict = {}


# ─────────────────────────────────────────────
# SCHEMAS
# ─────────────────────────────────────────────

class BrandConfigRequest(BaseModel):
    name:            str   = Field(..., min_length=1, max_length=50)
    tone:            str   = Field(..., min_length=1)
    audience:        str   = Field(..., min_length=1)
    cta:             str   = Field(..., min_length=1)
    subtitle_color:  str   = Field(..., description="Hex color e.g. #FF6B9D")
    hook_variants:   int   = Field(..., ge=1, le=10)
    video_duration:  int   = Field(25, ge=10, le=60)
    voice_speed:     float = Field(1.0, ge=0.7, le=1.5)
    clip_emotion_tags: Optional[list] = None

    @field_validator("name")
    @classmethod
    def name_not_whitespace(cls, v):
        if not v.strip():
            raise ValueError("name must not be empty or whitespace")
        return v.strip()

    @field_validator("subtitle_color")
    @classmethod
    def valid_hex_color(cls, v):
        if not re.match(r'^#[0-9A-Fa-f]{6}$', v):
            raise ValueError(
                f"subtitle_color must be a valid hex color (e.g. #FF6B9D), got: {v}"
            )
        return v


class BrandConfigResponse(BaseModel):
    brand_id: str
    name:     str
    message:  str


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def save_brand_config(tenant_id: str, brand_data: dict) -> dict:
    """Save brand config for a tenant. Separated for testability."""
    if tenant_id not in _tenant_brands:
        _tenant_brands[tenant_id] = []

    brand_id = str(uuid.uuid4())[:8]
    brand_record = {"brand_id": brand_id, **brand_data}
    _tenant_brands[tenant_id].append(brand_record)

    # Also add to brands.json in memory for script engine
    try:
        config_path = "config/brands.json"
        with open(config_path) as f:
            brands = json.load(f)
        brands[brand_data["name"]] = {
            "tone":                 brand_data.get("tone", "emotional"),
            "style":                "ugc_authentic",
            "audience":             brand_data.get("audience", "general"),
            "persona_name":         brand_data.get("persona_name", "Alex"),
            "persona_photo":        f"config/personas/{brand_data['name'].lower()}_persona.jpg",
            "voice_model":          f"config/voices/{brand_data['name'].lower()}.onnx",
            "voice_speed":          brand_data.get("voice_speed", 1.0),
            "subtitle_color":       brand_data.get("subtitle_color", "#00D4FF"),
            "subtitle_style":       "bold_centered_word_level",
            "hook_variants":        brand_data.get("hook_variants", 3),
            "video_duration_target": brand_data.get("video_duration", 25),
            "cta":                  brand_data.get("cta", ""),
            "brand_colors":         [brand_data.get("subtitle_color", "#00D4FF"), "#0A0E1A"],
            "clip_emotion_tags":    brand_data.get("clip_emotion_tags", ["general"]),
            "script_style_notes":   "",
            "hook_patterns":        [],
        }
        with open(config_path, 'w') as f:
            json.dump(brands, f, indent=2)
    except Exception as e:
        logger.warning(f"Could not update brands.json: {e}")

    return brand_record


def get_tenant_brands(tenant_id: str) -> list:
    """Get all brands for a tenant. Separated for testability."""
    return _tenant_brands.get(tenant_id, [])


def get_tenant_brand_count(tenant_id: str) -> int:
    """Get number of brands a tenant has configured."""
    return len(_tenant_brands.get(tenant_id, []))


def get_tenant_plan(tenant_id: str) -> str:
    """Get tenant's current plan. Separated for testability."""
    from api.middleware.credit_gate import get_tenant_from_api_key
    return "free"  # Default — replaced by real lookup in production


def check_onboarding_complete(tenant_id: str) -> dict:
    """Check if tenant has completed onboarding. Separated for testability."""
    brand_count = get_tenant_brand_count(tenant_id)
    has_brand   = brand_count > 0
    has_credits = True  # Always true after signup

    return {
        "complete":    has_brand and has_credits,
        "has_brand":   has_brand,
        "has_credits": has_credits,
        "brand_count": brand_count,
        "missing":     (["brand_config"] if not has_brand else []),
    }


def _get_tenant_id_from_request(request: Request) -> str:
    """Extract tenant ID from request. Uses API key → tenant lookup."""
    api_key = request.headers.get("X-API-Key", "")
    from api.middleware.credit_gate import get_tenant_from_api_key
    tenant = get_tenant_from_api_key(api_key)
    return tenant["id"] if tenant else "unknown"


def _check_brand_limit(tenant_id: str, plan: str) -> bool:
    """Returns True if tenant can add another brand under their plan"""
    config     = billing.get_plan_config(plan)
    max_brands = config["max_brands"]
    if max_brands == -1:
        return True  # Unlimited
    current = get_tenant_brand_count(tenant_id)
    return current < max_brands


# ─────────────────────────────────────────────
# ROUTES
# ─────────────────────────────────────────────

@router.post("/onboarding/brand", response_model=BrandConfigResponse, status_code=201)
async def create_brand(
    brand_config: BrandConfigRequest,
    request: Request,
) -> BrandConfigResponse:
    """
    Create a new brand configuration for the tenant.

    Free plan: 1 brand max
    Starter:   1 brand
    Pro:       5 brands
    Agency:    Unlimited

    Returns brand_id on success.
    Raises 402 if plan brand limit reached.
    """
    tenant_id = _get_tenant_id_from_request(request)
    plan      = get_tenant_plan(tenant_id)

    if not _check_brand_limit(tenant_id, plan):
        config     = billing.get_plan_config(plan)
        max_brands = config["max_brands"]
        raise HTTPException(
            status_code=402,
            detail=(
                f"Brand limit reached for {plan} plan ({max_brands} brands). "
                f"Upgrade to Pro for up to 5 brands, or Agency for unlimited. "
                f"cast.tinlance.com/pricing"
            )
        )

    brand_data = brand_config.model_dump()
    saved      = save_brand_config(tenant_id, brand_data)

    logger.info(
        f"Brand created | tenant={tenant_id[:8]} | "
        f"name={brand_config.name}"
    )

    return BrandConfigResponse(
        brand_id=saved["brand_id"],
        name=brand_config.name,
        message=f"Brand '{brand_config.name}' configured successfully.",
    )


@router.get("/onboarding/brands")
async def list_brands(request: Request) -> list:
    """
    List all brands configured by this tenant.
    """
    tenant_id = _get_tenant_id_from_request(request)
    brands    = get_tenant_brands(tenant_id)
    return brands


@router.get("/onboarding/complete")
async def check_complete(request: Request) -> dict:
    """
    Check if the tenant has completed initial setup.

    Returns:
        {complete: bool, has_brand: bool, has_credits: bool, missing: list}
    """
    tenant_id = _get_tenant_id_from_request(request)
    return check_onboarding_complete(tenant_id)
