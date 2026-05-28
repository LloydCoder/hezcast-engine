"""HezCast Engine — Status Route"""

import logging
from fastapi import APIRouter, HTTPException
from api.schemas import JobStatusResponse
from api.routes.generate import _jobs

router = APIRouter(tags=["Pipeline"])
logger = logging.getLogger(__name__)


def get_job(job_id: str) -> dict | None:
    """Retrieve job by ID. Separated for testability."""
    return _jobs.get(job_id)


@router.get("/status/{job_id}", response_model=JobStatusResponse)
def get_job_status(job_id: str):
    """
    Poll job status and retrieve output when complete.

    Status flow:
      queued → generating_hooks → awaiting_selection →
      processing → composing → qa_check → completed
    """
    job = get_job(job_id)

    if job is None:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")

    return JobStatusResponse(
        job_id=         job["job_id"],
        status=         job["status"],
        brand=          job.get("brand", ""),
        topic=          job.get("topic", ""),
        output_path=    job.get("output_path"),
        output_url=     job.get("output_url"),
        duration_sec=   job.get("duration_sec"),
        render_time_ms= job.get("render_time_ms"),
        qa_passed=      job.get("qa_passed"),
        llm_used=       job.get("llm_used"),
        error_message=  job.get("error_message"),
    )
