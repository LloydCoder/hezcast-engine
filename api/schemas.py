"""
HezCast Engine — API Schemas
Tinlance Limited | Apache 2.0
"""

from pydantic import BaseModel, Field, field_validator
from typing import Optional, List
from enum import Enum


VALID_BRANDS = {"GiftMode", "Tinlance", "WebTemify", "HezCast"}

VALID_STATUSES = {
    "queued", "generating_hooks", "awaiting_selection",
    "processing", "composing", "qa_check",
    "completed", "failed", "needs_review"
}


# ─────────────────────────────────────────────
# REQUEST SCHEMAS
# ─────────────────────────────────────────────

class GenerateRequest(BaseModel):
    topic: Optional[str] = Field(None, description="Pain point or scenario")
    url:   Optional[str] = Field(None, description="URL to convert to video")
    brand: str = Field(..., description="Brand name")
    tone:  Optional[str] = Field(None, description="Tone override")

    @field_validator("brand")
    @classmethod
    def brand_must_be_valid(cls, v):
        if v not in VALID_BRANDS:
            raise ValueError(
                f"Unknown brand '{v}'. Valid brands: {sorted(VALID_BRANDS)}"
            )
        return v

    @field_validator("topic")
    @classmethod
    def topic_not_whitespace(cls, v):
        if v is not None and not v.strip():
            raise ValueError("topic must not be empty or whitespace")
        return v.strip() if v else v

    def model_post_init(self, __context) -> None:
        """Require at least one of topic or url"""
        topic_empty = not self.topic or not self.topic.strip()
        url_empty   = not self.url or not self.url.strip()
        if topic_empty and url_empty:
            raise ValueError(
                "Either topic or url is required. "
                "Provide a topic string or a URL to convert to video."
            )

    def get_topic(self) -> str:
        """Returns topic from direct input or URL preprocessing"""
        return (self.topic or "").strip()


class SelectHookRequest(BaseModel):
    variant_num: int = Field(..., ge=1, description="1-indexed hook variant to select")


# ─────────────────────────────────────────────
# RESPONSE SCHEMAS
# ─────────────────────────────────────────────

class GenerateResponse(BaseModel):
    job_id: str
    status: str


class JobStatusResponse(BaseModel):
    job_id:          str
    status:          str
    brand:           str
    topic:           str
    output_path:     Optional[str] = None
    output_url:      Optional[str] = None
    duration_sec:    Optional[float] = None
    render_time_ms:  Optional[int] = None
    qa_passed:       Optional[bool] = None
    llm_used:        Optional[str] = None
    error_message:   Optional[str] = None


class HookVariantResponse(BaseModel):
    variant_num: int
    hook_text:   str
    selected:    bool = False


class SelectHookResponse(BaseModel):
    job_id: str
    status: str
    selected_variant: int


class BrandResponse(BaseModel):
    name:            str
    tone:            str
    style:           str
    audience:        str
    persona_name:    str
    hook_variants:   int
    video_duration_target: int
    subtitle_color:  str


class HealthResponse(BaseModel):
    status:   str
    version:  str
    services: dict
