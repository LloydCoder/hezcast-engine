"""HezCast Engine — Hooks Route"""

import logging
from fastapi import APIRouter, HTTPException
from api.schemas import HookVariantResponse, SelectHookRequest, SelectHookResponse
from api.routes.generate import _jobs, _hooks_store

router = APIRouter(tags=["Pipeline"])
logger = logging.getLogger(__name__)


def get_hooks(job_id: str) -> list | None:
    """Retrieve hook variants for a job. Separated for testability."""
    return _hooks_store.get(job_id)


def select_hook_and_render(job_id: str, variant_num: int) -> dict:
    """
    Mark hook as selected and trigger render pipeline.
    Separated for testability.
    """
    job = _jobs.get(job_id)
    if not job:
        return None

    hooks = _hooks_store.get(job_id, [])
    selected = next((h for h in hooks if h["variant_num"] == variant_num), None)
    if not selected:
        raise ValueError(f"Variant {variant_num} not found")

    # Mark selected
    selected["selected"] = True
    job["selected_hook_num"] = variant_num
    job["selected_script"]   = selected.get("full_script", "")
    job["status"] = "processing"

    # Dispatch render chain to Celery
    try:
        from workers.tasks import synthesize_voice_task
        synthesize_voice_task.delay(job)
    except Exception as e:
        logger.warning(f"Celery render dispatch failed: {e}")

    return {"job_id": job_id, "status": "processing"}


@router.get("/hooks/{job_id}", response_model=list[HookVariantResponse])
def get_hook_variants(job_id: str):
    """
    Get all A/B hook variants for a job.

    Available once job reaches awaiting_selection status.
    Select your preferred hook via POST /hooks/{job_id}/select.
    """
    if job_id not in _jobs:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")

    hooks = get_hooks(job_id)
    if hooks is None:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")

    return [
        HookVariantResponse(
            variant_num=h["variant_num"],
            hook_text=h["hook_text"],
            selected=h.get("selected", False),
        )
        for h in hooks
    ]


@router.post("/hooks/{job_id}/select", response_model=SelectHookResponse, status_code=202)
def select_hook(job_id: str, request: SelectHookRequest):
    """
    Select a hook variant and trigger video render.

    This starts the full render pipeline:
      voice → clip → compose → subtitles → QA → MP4

    Poll GET /status/{job_id} to track progress.
    """
    if job_id not in _jobs:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")

    try:
        result = select_hook_and_render(job_id, request.variant_num)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    return SelectHookResponse(
        job_id=job_id,
        status="processing",
        selected_variant=request.variant_num,
    )
