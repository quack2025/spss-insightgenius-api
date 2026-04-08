"""Variable Groups API — CRUD + auto-detect."""

import asyncio
import logging
from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth_unified import AuthContext, require_user
from db.database import get_db
from db.models.variable_group import VariableGroup
from schemas.variable_groups import VariableGroupCreate, VariableGroupUpdate, VariableGroupOut
from services.project_service import ProjectAccessError, get_project
from shared.response import error_response, success_response

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/projects/{project_id}/variable-groups", tags=["Variable Groups"])


@router.post("")
async def create_group(
    project_id: UUID, data: VariableGroupCreate,
    auth: AuthContext = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    try:
        await get_project(db, project_id, auth.db_user)
    except ProjectAccessError as e:
        return JSONResponse(status_code=404, content=error_response("NOT_FOUND", str(e)))

    group = VariableGroup(
        project_id=project_id, name=data.name, display_name=data.display_name,
        group_type=data.group_type, variables=data.variables,
    )
    db.add(group)
    await db.flush()
    return success_response(VariableGroupOut.model_validate(group).model_dump(mode="json"))


@router.get("")
async def list_groups(
    project_id: UUID,
    auth: AuthContext = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    try:
        await get_project(db, project_id, auth.db_user)
    except ProjectAccessError as e:
        return JSONResponse(status_code=404, content=error_response("NOT_FOUND", str(e)))

    result = await db.execute(
        select(VariableGroup).where(VariableGroup.project_id == project_id)
    )
    groups = result.scalars().all()
    return success_response([VariableGroupOut.model_validate(g).model_dump(mode="json") for g in groups])


@router.put("/{group_id}")
async def update_group(
    project_id: UUID, group_id: UUID, data: VariableGroupUpdate,
    auth: AuthContext = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    try:
        await get_project(db, project_id, auth.db_user)
    except ProjectAccessError as e:
        return JSONResponse(status_code=404, content=error_response("NOT_FOUND", str(e)))

    result = await db.execute(
        select(VariableGroup).where(VariableGroup.id == group_id, VariableGroup.project_id == project_id)
    )
    group = result.scalar_one_or_none()
    if not group:
        return JSONResponse(status_code=404, content=error_response("NOT_FOUND", "Group not found"))

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(group, field, value)
    await db.flush()
    return success_response(VariableGroupOut.model_validate(group).model_dump(mode="json"))


@router.delete("/{group_id}")
async def delete_group(
    project_id: UUID, group_id: UUID,
    auth: AuthContext = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    try:
        await get_project(db, project_id, auth.db_user)
    except ProjectAccessError as e:
        return JSONResponse(status_code=404, content=error_response("NOT_FOUND", str(e)))

    result = await db.execute(
        select(VariableGroup).where(VariableGroup.id == group_id, VariableGroup.project_id == project_id)
    )
    group = result.scalar_one_or_none()
    if not group:
        return JSONResponse(status_code=404, content=error_response("NOT_FOUND", "Group not found"))

    await db.delete(group)
    await db.flush()
    return success_response(None)


@router.post("/auto-detect")
async def auto_detect_groups(
    project_id: UUID,
    auth: AuthContext = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    """Auto-detect variable groups (MRS, grids) using QuantipyMRX."""
    try:
        project = await get_project(db, project_id, auth.db_user)
    except ProjectAccessError as e:
        return JSONResponse(status_code=404, content=error_response("NOT_FOUND", str(e)))

    from services.data_manager import get_project_data
    try:
        spss_data = await get_project_data(str(project_id))
    except Exception as e:
        return JSONResponse(status_code=400, content=error_response("NO_DATA", str(e)))

    # Auto-detect via MRX with timeout
    from services.quantipy_engine import QuantiProEngine
    try:
        detect_result = await asyncio.wait_for(
            asyncio.to_thread(QuantiProEngine.auto_detect, spss_data),
            timeout=30,
        )
    except asyncio.TimeoutError:
        return JSONResponse(status_code=504, content=error_response("TIMEOUT", "Auto-detect timed out"))
    except Exception as e:
        return JSONResponse(status_code=500, content=error_response("DETECTION_FAILED", str(e)))

    detected_groups = detect_result.get("detected_groups", []) if detect_result else []
    return success_response({"detected_groups": detected_groups})
