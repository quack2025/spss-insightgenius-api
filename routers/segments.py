"""Segments API — reusable audience filter CRUD + preview."""

import logging
from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth_unified import AuthContext, require_user
from db.database import get_db
from db.models.segment import Segment
from schemas.segments import SegmentCreate, SegmentUpdate, SegmentOut, SegmentPreviewRequest
from services.project_service import ProjectAccessError, get_project
from shared.response import error_response, success_response

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/projects/{project_id}/segments", tags=["Segments"])

MAX_SEGMENTS_PER_PROJECT = 20


@router.post("")
async def create_segment(
    project_id: UUID, data: SegmentCreate,
    auth: AuthContext = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    try:
        await get_project(db, project_id, auth.db_user)
    except ProjectAccessError as e:
        return JSONResponse(status_code=404, content=error_response("NOT_FOUND", str(e)))

    count_result = await db.execute(
        select(Segment).where(Segment.project_id == project_id)
    )
    if len(count_result.all()) >= MAX_SEGMENTS_PER_PROJECT:
        return JSONResponse(status_code=400, content=error_response(
            "LIMIT_REACHED", f"Maximum {MAX_SEGMENTS_PER_PROJECT} segments per project"))

    segment = Segment(project_id=project_id, name=data.name, conditions=data.conditions)
    db.add(segment)
    await db.flush()
    return success_response(SegmentOut.model_validate(segment).model_dump(mode="json"))


@router.get("")
async def list_segments(
    project_id: UUID,
    auth: AuthContext = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    try:
        await get_project(db, project_id, auth.db_user)
    except ProjectAccessError as e:
        return JSONResponse(status_code=404, content=error_response("NOT_FOUND", str(e)))

    result = await db.execute(
        select(Segment).where(Segment.project_id == project_id)
    )
    segments = result.scalars().all()
    return success_response([SegmentOut.model_validate(s).model_dump(mode="json") for s in segments])


@router.put("/{segment_id}")
async def update_segment(
    project_id: UUID, segment_id: UUID, data: SegmentUpdate,
    auth: AuthContext = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    try:
        await get_project(db, project_id, auth.db_user)
    except ProjectAccessError as e:
        return JSONResponse(status_code=404, content=error_response("NOT_FOUND", str(e)))

    result = await db.execute(
        select(Segment).where(Segment.id == segment_id, Segment.project_id == project_id)
    )
    segment = result.scalar_one_or_none()
    if not segment:
        return JSONResponse(status_code=404, content=error_response("NOT_FOUND", "Segment not found"))

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(segment, field, value)
    await db.flush()
    return success_response(SegmentOut.model_validate(segment).model_dump(mode="json"))


@router.delete("/{segment_id}")
async def delete_segment(
    project_id: UUID, segment_id: UUID,
    auth: AuthContext = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    try:
        await get_project(db, project_id, auth.db_user)
    except ProjectAccessError as e:
        return JSONResponse(status_code=404, content=error_response("NOT_FOUND", str(e)))

    result = await db.execute(
        select(Segment).where(Segment.id == segment_id, Segment.project_id == project_id)
    )
    segment = result.scalar_one_or_none()
    if not segment:
        return JSONResponse(status_code=404, content=error_response("NOT_FOUND", "Segment not found"))

    await db.delete(segment)
    await db.flush()
    return success_response(None)


@router.post("/preview")
async def preview_segment(
    project_id: UUID, data: SegmentPreviewRequest,
    auth: AuthContext = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    """Preview how many rows match the segment conditions."""
    try:
        await get_project(db, project_id, auth.db_user)
    except ProjectAccessError as e:
        return JSONResponse(status_code=404, content=error_response("NOT_FOUND", str(e)))

    from services.data_manager import get_project_data
    from services.segment_service import preview_segment as _preview

    try:
        spss_data = await get_project_data(str(project_id))
    except Exception as e:
        return JSONResponse(status_code=400, content=error_response("NO_DATA", str(e)))

    result = _preview(spss_data.df, data.conditions)
    return success_response(result)
