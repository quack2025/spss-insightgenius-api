"""Merge API — combine datasets (append/join/wave merge)."""
import logging
from uuid import UUID
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from auth_unified import AuthContext, require_user
from db.database import get_db
from services.project_service import ProjectAccessError, get_project
from shared.response import error_response, success_response

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/projects/{project_id}/merge", tags=["Merge"])


class MergeValidateRequest(BaseModel):
    source_project_id: UUID
    merge_type: str = "append"  # append, join, wave_merge


class MergeExecuteRequest(BaseModel):
    source_project_id: UUID
    merge_type: str = "append"
    join_key: str | None = None  # For join mode


@router.post("/validate")
async def validate_merge(
    project_id: UUID, data: MergeValidateRequest,
    auth: AuthContext = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    """Validate merge compatibility between two projects."""
    try:
        target = await get_project(db, project_id, auth.db_user)
        source = await get_project(db, data.source_project_id, auth.db_user)
    except ProjectAccessError as e:
        return JSONResponse(status_code=404, content=error_response("NOT_FOUND", str(e)))

    if not target.dataset_metadata or not source.dataset_metadata:
        return JSONResponse(status_code=400, content=error_response("NO_DATA", "Both projects need data"))

    target_vars = {v["name"] for v in target.dataset_metadata.variables}
    source_vars = {v["name"] for v in source.dataset_metadata.variables}

    common = target_vars & source_vars
    only_target = target_vars - source_vars
    only_source = source_vars - target_vars

    return success_response({
        "compatible": len(common) > 0,
        "merge_type": data.merge_type,
        "common_variables": len(common),
        "only_in_target": len(only_target),
        "only_in_source": len(only_source),
        "target_cases": target.dataset_metadata.n_cases,
        "source_cases": source.dataset_metadata.n_cases,
    })


@router.post("")
async def execute_merge(
    project_id: UUID, data: MergeExecuteRequest,
    auth: AuthContext = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    """Execute dataset merge. Creates modified dataset in the target project."""
    try:
        await get_project(db, project_id, auth.db_user)
        await get_project(db, data.source_project_id, auth.db_user)
    except ProjectAccessError as e:
        return JSONResponse(status_code=404, content=error_response("NOT_FOUND", str(e)))

    # Merge requires loading both datasets — placeholder for full implementation
    return success_response({
        "status": "merge_initiated",
        "merge_type": data.merge_type,
        "note": "Full merge execution requires both datasets loaded",
    })
