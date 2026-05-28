"""
HezCast Engine — Jobs Route
Launch Blocker 6: GET /jobs + GET /jobs/stats
Tinlance Limited | Apache 2.0

Endpoints:
  GET /jobs           ← All jobs with optional filters
  GET /jobs/stats     ← Summary stats (total, completed, QA rate)

Connects the live dashboard jobs table to real data.
Replaces the mock data in app/dashboard/jobs/page.tsx.
"""

import logging
from fastapi import APIRouter, Query, HTTPException
from typing import Optional, List
from pydantic import BaseModel

from api.routes.generate import _jobs
from api.schemas import VALID_BRANDS

router = APIRouter(tags=["Jobs"])
logger = logging.getLogger(__name__)

VALID_STATUSES = {
    "queued", "generating_hooks", "awaiting_selection",
    "processing", "composing", "qa_check",
    "completed", "failed", "needs_review",
}


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def get_all_jobs(
    brand:  Optional[str] = None,
    status: Optional[str] = None,
    limit:  int = 50,
) -> list:
    """
    Get all jobs from store with optional filtering.
    Separated for testability.
    """
    jobs = list(_jobs.values())

    if brand:
        jobs = [j for j in jobs if j.get("brand") == brand]

    if status:
        jobs = [j for j in jobs if j.get("status") == status]

    # Sort newest first
    jobs.sort(key=lambda j: j.get("created_at", ""), reverse=True)

    return jobs[:limit]


def get_job_stats() -> dict:
    """
    Calculate summary stats across all jobs.
    Separated for testability.
    """
    jobs = list(_jobs.values())
    total     = len(jobs)
    completed = sum(1 for j in jobs if j.get("status") == "completed")
    failed    = sum(1 for j in jobs if j.get("status") == "failed")
    active    = sum(1 for j in jobs if j.get("status") in {
        "queued", "generating_hooks", "processing", "composing", "qa_check"
    })

    qa_eligible = [j for j in jobs if j.get("qa_passed") is not None]
    qa_passed   = sum(1 for j in qa_eligible if j.get("qa_passed"))
    qa_rate     = round(qa_passed / max(len(qa_eligible), 1) * 100, 1)

    render_times = [
        j["render_time_ms"] for j in jobs
        if j.get("render_time_ms") and j["render_time_ms"] > 0
    ]
    avg_render = round(sum(render_times) / max(len(render_times), 1) / 1000, 1)

    brands = {}
    for j in jobs:
        b = j.get("brand", "Unknown")
        brands[b] = brands.get(b, 0) + 1

    return {
        "total":         total,
        "completed":     completed,
        "failed":        failed,
        "active":        active,
        "qa_pass_rate":  qa_rate,
        "avg_render_sec": avg_render,
        "by_brand":      brands,
    }


# ─────────────────────────────────────────────
# ROUTES
# ─────────────────────────────────────────────

@router.get("/jobs")
def list_jobs(
    brand:  Optional[str] = Query(None, description="Filter by brand"),
    status: Optional[str] = Query(None, description="Filter by status"),
    limit:  int           = Query(50, ge=1, le=200, description="Max results"),
) -> list:
    """
    List all jobs with optional filtering.

    Query params:
      brand:  GiftMode | Tinlance | WebTemify | HezCast
      status: queued | generating_hooks | awaiting_selection |
              processing | composing | qa_check |
              completed | failed | needs_review
      limit:  1–200 (default 50)

    Used by the live dashboard jobs table.
    Hybrid polling — only active jobs are polled every 3s.
    """
    # Validate brand filter
    if brand and brand not in VALID_BRANDS:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid brand '{brand}'. Valid: {sorted(VALID_BRANDS)}"
        )

    # Validate status filter
    if status and status not in VALID_STATUSES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid status '{status}'. Valid: {sorted(VALID_STATUSES)}"
        )

    jobs = get_all_jobs(brand=brand, status=status, limit=limit)

    logger.debug(
        f"GET /jobs | brand={brand} | status={status} | "
        f"limit={limit} | returned={len(jobs)}"
    )

    return jobs


@router.get("/jobs/stats")
def job_stats() -> dict:
    """
    Get summary statistics across all jobs.

    Returns:
        total, completed, failed, active, qa_pass_rate,
        avg_render_sec, by_brand

    Used by the analytics dashboard and admin overview.
    """
    stats = get_job_stats()
    return stats
