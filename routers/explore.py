"""Explore Mode API — interactive point-and-click analysis."""

import asyncio
import logging
from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth_unified import AuthContext, require_user
from db.database import get_db
from db.models.explore_bookmark import ExploreBookmark
from schemas.explore import ExploreRunRequest, BookmarkCreate, BookmarkOut
from services.project_service import ProjectAccessError, get_project
from shared.response import error_response, success_response

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/projects/{project_id}/explore", tags=["Explore"])


@router.get("/variables")
async def list_variables(
    project_id: UUID,
    auth: AuthContext = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    """List available variables for the variable picker."""
    try:
        project = await get_project(db, project_id, auth.db_user)
    except ProjectAccessError as e:
        return JSONResponse(status_code=404, content=error_response("NOT_FOUND", str(e)))

    if not project.dataset_metadata:
        return JSONResponse(status_code=400, content=error_response("NO_DATA", "No dataset uploaded"))

    variables = project.dataset_metadata.enriched_variables
    return success_response(variables)


@router.post("/run")
async def run_analysis(
    project_id: UUID, data: ExploreRunRequest,
    auth: AuthContext = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    """Run a single analysis (no AI — direct execution via quantipy_engine)."""
    try:
        project = await get_project(db, project_id, auth.db_user)
    except ProjectAccessError as e:
        return JSONResponse(status_code=404, content=error_response("NOT_FOUND", str(e)))

    from services.data_manager import get_project_data
    from services.nl_chat.executor import execute_analysis_plan

    try:
        spss_data = await get_project_data(str(project_id))
    except Exception as e:
        return JSONResponse(status_code=400, content=error_response("NO_DATA", str(e)))

    # Apply segment filter if provided
    if data.segment_id:
        from services.segment_service import resolve_segment_filter
        seg_result = await db.execute(
            select(db.models.segment.Segment).where(
                db.models.segment.Segment.id == data.segment_id
            )
        )
        segment = seg_result.scalar_one_or_none()
        if segment:
            spss_data.df = resolve_segment_filter(spss_data.df, segment.conditions)

    plan = [{
        "type": data.analysis_type,
        "variable": data.variable,
        "cross_variable": data.cross_variable,
        "weight": data.weight,
        "significance_level": data.significance_level,
    }]

    results = await execute_analysis_plan(spss_data, plan, project.low_base_threshold)

    if results and results[0]["success"]:
        return success_response(results[0])
    elif results:
        return JSONResponse(status_code=400, content=error_response("ANALYSIS_FAILED", results[0].get("error", "Unknown error")))
    return JSONResponse(status_code=500, content=error_response("NO_RESULTS", "No results returned"))


@router.post("/bookmarks")
async def create_bookmark(
    project_id: UUID, data: BookmarkCreate,
    auth: AuthContext = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    try:
        await get_project(db, project_id, auth.db_user)
    except ProjectAccessError as e:
        return JSONResponse(status_code=404, content=error_response("NOT_FOUND", str(e)))

    bookmark = ExploreBookmark(
        project_id=project_id, user_id=auth.db_user.id,
        name=data.name, config=data.config,
    )
    db.add(bookmark)
    await db.flush()
    return success_response(BookmarkOut.model_validate(bookmark).model_dump(mode="json"))


@router.get("/bookmarks")
async def list_bookmarks(
    project_id: UUID,
    auth: AuthContext = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    try:
        await get_project(db, project_id, auth.db_user)
    except ProjectAccessError as e:
        return JSONResponse(status_code=404, content=error_response("NOT_FOUND", str(e)))

    result = await db.execute(
        select(ExploreBookmark).where(
            ExploreBookmark.project_id == project_id,
            ExploreBookmark.user_id == auth.db_user.id,
        )
    )
    bookmarks = result.scalars().all()
    return success_response([BookmarkOut.model_validate(b).model_dump(mode="json") for b in bookmarks])


@router.delete("/bookmarks/{bookmark_id}")
async def delete_bookmark(
    project_id: UUID, bookmark_id: UUID,
    auth: AuthContext = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    try:
        await get_project(db, project_id, auth.db_user)
    except ProjectAccessError as e:
        return JSONResponse(status_code=404, content=error_response("NOT_FOUND", str(e)))

    result = await db.execute(
        select(ExploreBookmark).where(ExploreBookmark.id == bookmark_id)
    )
    bookmark = result.scalar_one_or_none()
    if not bookmark:
        return JSONResponse(status_code=404, content=error_response("NOT_FOUND", "Bookmark not found"))

    await db.delete(bookmark)
    await db.flush()
    return success_response(None)
