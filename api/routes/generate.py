"""HezCast Engine — Generate Route"""

import uuid
import logging
from fastapi import APIRouter, HTTPException
from api.schemas import GenerateRequest, GenerateResponse

router = APIRouter(tags=["Pipeline"])
logger = logging.getLogger(__name__)

# In-memory job store (replaced by DB in production)
_jobs: dict = {}
_hooks_store: dict = {}


def submit_job(request: GenerateRequest) -> dict:
    """
    Create a new job record and dispatch to Celery.
    Handles both direct topic and URL-to-video requests.
    Separated for testability.
    """
    job_id = str(uuid.uuid4())

    # Resolve topic — either direct or from URL
    topic = request.get_topic()
    if not topic and request.url:
        try:
            from core.url_preprocessor import URLPreprocessor
            preprocessor = URLPreprocessor()
            topic = preprocessor.process_url(request.url)
            logger.info(f"URL preprocessed | url={request.url[:50]} | topic={topic[:50]}")
        except Exception as e:
            logger.warning(f"URL preprocessing failed: {e}")
            topic = request.url  # fallback: use URL as topic

    if not topic:
        topic = "general content"

    job = {
        "job_id":    job_id,
        "brand":     request.brand,
        "topic":     topic,
        "source_url": request.url or "",
        "tone":      request.tone or "",
        "status":    "queued",
    }

    _jobs[job_id] = job

    # Dispatch to Celery — import here to avoid circular imports
    try:
        from workers.tasks import generate_hooks_task
        generate_hooks_task.delay(job)
    except Exception as e:
        logger.warning(f"Celery dispatch failed, running sync: {e}")
        # Sync fallback for environments without Celery
        try:
            from workers.tasks import generate_hooks_task
            generate_hooks_task(job)
        except Exception:
            pass

    logger.info(f"Job submitted | id={job_id} | brand={request.brand}")
    return job


@router.post("/generate", response_model=GenerateResponse, status_code=202)
def generate_video(request: GenerateRequest):
    """
    Submit a new video generation job.

    Returns job_id immediately. Use GET /status/{job_id} to poll progress.
    Use GET /hooks/{job_id} to view A/B hook variants.
    """
    result = submit_job(request)
    return GenerateResponse(job_id=result["job_id"], status=result["status"])
