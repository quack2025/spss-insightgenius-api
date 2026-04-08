"""Waves API — CRUD + wave comparison."""

import logging
from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth_unified import AuthContext, require_user
from db.database import get_db
from db.models.wave import ProjectWave
from schemas.waves import WaveCreate, WaveUpdate, WaveOut, WaveCompareRequest
from services.project_service import ProjectAccessError, get_project
from shared.response import error_response, success_response

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/projects/{project_id}/waves", tags=["Waves"])


@router.post("")
async def create_wave(
    project_id: UUID, data: WaveCreate,
    auth: AuthContext = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    try:
        await get_project(db, project_id, auth.db_user)
    except ProjectAccessError as e:
        return JSONResponse(status_code=404, content=error_response("NOT_FOUND", str(e)))

    wave = ProjectWave(
        project_id=project_id, wave_name=data.wave_name,
        wave_order=data.wave_order, file_id=data.file_id,
    )
    db.add(wave)
    await db.flush()
    return success_response(WaveOut.model_validate(wave).model_dump(mode="json"))


@router.get("")
async def list_waves(
    project_id: UUID,
    auth: AuthContext = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    try:
        await get_project(db, project_id, auth.db_user)
    except ProjectAccessError as e:
        return JSONResponse(status_code=404, content=error_response("NOT_FOUND", str(e)))

    result = await db.execute(
        select(ProjectWave).where(ProjectWave.project_id == project_id).order_by(ProjectWave.wave_order)
    )
    waves = result.scalars().all()
    return success_response([WaveOut.model_validate(w).model_dump(mode="json") for w in waves])


@router.put("/{wave_id}")
async def update_wave(
    project_id: UUID, wave_id: UUID, data: WaveUpdate,
    auth: AuthContext = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    try:
        await get_project(db, project_id, auth.db_user)
    except ProjectAccessError as e:
        return JSONResponse(status_code=404, content=error_response("NOT_FOUND", str(e)))

    result = await db.execute(
        select(ProjectWave).where(ProjectWave.id == wave_id, ProjectWave.project_id == project_id)
    )
    wave = result.scalar_one_or_none()
    if not wave:
        return JSONResponse(status_code=404, content=error_response("NOT_FOUND", "Wave not found"))

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(wave, field, value)
    await db.flush()
    return success_response(WaveOut.model_validate(wave).model_dump(mode="json"))


@router.delete("/{wave_id}")
async def delete_wave(
    project_id: UUID, wave_id: UUID,
    auth: AuthContext = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    try:
        await get_project(db, project_id, auth.db_user)
    except ProjectAccessError as e:
        return JSONResponse(status_code=404, content=error_response("NOT_FOUND", str(e)))

    result = await db.execute(
        select(ProjectWave).where(ProjectWave.id == wave_id, ProjectWave.project_id == project_id)
    )
    wave = result.scalar_one_or_none()
    if not wave:
        return JSONResponse(status_code=404, content=error_response("NOT_FOUND", "Wave not found"))

    await db.delete(wave)
    await db.flush()
    return success_response(None)


@router.post("/compare")
async def compare_waves(
    project_id: UUID, data: WaveCompareRequest,
    auth: AuthContext = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    """Compare a metric across waves — delegates to existing wave_comparison service."""
    try:
        await get_project(db, project_id, auth.db_user)
    except ProjectAccessError as e:
        return JSONResponse(status_code=404, content=error_response("NOT_FOUND", str(e)))

    # Wave comparison needs data from multiple files — placeholder for now
    return success_response({"note": "Wave comparison requires multi-file data loading", "variable": data.variable})
