"""GET /v1/jobs/{job_id} — Poll async job status."""

import logging

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from auth import require_auth, KeyConfig
from shared.job_store import JobStore

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Jobs"])

_store = JobStore()


@router.get("/v1/jobs/{job_id}", summary="Get async job status")
async def get_job(job_id: str, key: KeyConfig = Depends(require_auth)):
    job = _store.get(job_id)
    if not job:
        return JSONResponse(status_code=404, content={
            "success": False,
            "error": {"code": "NOT_FOUND", "message": f"Job {job_id} not found"},
        })
    # Ownership check — users can only see their own jobs
    if job.get("user_id") and job["user_id"] != key.name:
        return JSONResponse(status_code=404, content={
            "success": False,
            "error": {"code": "NOT_FOUND", "message": f"Job {job_id} not found"},
        })
    return {"success": True, "data": job}
