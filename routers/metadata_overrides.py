"""Metadata Overrides API — user-defined variable labels and value labels."""

import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from auth_unified import AuthContext, require_user
from db.database import get_db
from services.project_service import ProjectAccessError, get_project
from shared.response import error_response, success_response

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/projects/{project_id}/metadata", tags=["Metadata"])


@router.get("/overrides")
async def get_overrides(
    project_id: UUID,
    auth: AuthContext = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    """Get all user-defined metadata overrides."""
    try:
        project = await get_project(db, project_id, auth.db_user)
    except ProjectAccessError as e:
        return JSONResponse(status_code=404, content=error_response("NOT_FOUND", str(e)))

    if not project.dataset_metadata:
        return JSONResponse(status_code=400, content=error_response("NO_DATA", "No dataset uploaded"))

    return success_response(project.dataset_metadata.user_metadata_overrides or {})


@router.put("/overrides")
async def update_overrides(
    project_id: UUID, overrides: dict[str, Any],
    auth: AuthContext = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    """Bulk update metadata overrides."""
    try:
        project = await get_project(db, project_id, auth.db_user)
    except ProjectAccessError as e:
        return JSONResponse(status_code=404, content=error_response("NOT_FOUND", str(e)))

    if not project.dataset_metadata:
        return JSONResponse(status_code=400, content=error_response("NO_DATA", "No dataset uploaded"))

    project.dataset_metadata.user_metadata_overrides = overrides
    await db.flush()
    return success_response(overrides)
