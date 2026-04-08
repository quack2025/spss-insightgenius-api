"""Exports API — create/list project exports + banner/stub variable listings."""

import logging
from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth_unified import AuthContext, require_user
from db.database import get_db
from db.models.export import Export, ExportStatus, ExportType
from schemas.exports import ExportCreate, ExportOut
from services.project_service import ProjectAccessError, get_project
from shared.response import error_response, success_response

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/projects/{project_id}/exports", tags=["Exports"])


@router.post("")
async def create_export(
    project_id: UUID, data: ExportCreate,
    auth: AuthContext = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    """Create a new export job."""
    try:
        await get_project(db, project_id, auth.db_user)
    except ProjectAccessError as e:
        return JSONResponse(status_code=404, content=error_response("NOT_FOUND", str(e)))

    export = Export(
        project_id=project_id,
        export_type=ExportType(data.export_type),
        status=ExportStatus.PENDING,
        config=data.config,
    )
    db.add(export)
    await db.flush()
    return success_response(ExportOut.model_validate(export).model_dump(mode="json"))


@router.get("")
async def list_exports(
    project_id: UUID,
    auth: AuthContext = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    try:
        await get_project(db, project_id, auth.db_user)
    except ProjectAccessError as e:
        return JSONResponse(status_code=404, content=error_response("NOT_FOUND", str(e)))

    result = await db.execute(
        select(Export).where(Export.project_id == project_id).order_by(Export.created_at.desc())
    )
    exports = result.scalars().all()
    return success_response([ExportOut.model_validate(e).model_dump(mode="json") for e in exports])


@router.get("/banners")
async def get_banner_variables(
    project_id: UUID,
    auth: AuthContext = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    """Get variables suitable as banners (categorical, 2-10 categories)."""
    try:
        project = await get_project(db, project_id, auth.db_user)
    except ProjectAccessError as e:
        return JSONResponse(status_code=404, content=error_response("NOT_FOUND", str(e)))

    if not project.dataset_metadata:
        return JSONResponse(status_code=400, content=error_response("NO_DATA", "No dataset uploaded"))

    banners = []
    for v in project.dataset_metadata.enriched_variables:
        vl = v.get("value_labels", {})
        if vl and 2 <= len(vl) <= 10:
            banners.append({
                "name": v["name"],
                "label": v.get("label", ""),
                "n_categories": len(vl),
            })
    return success_response(banners)


@router.get("/stubs")
async def get_analysis_variables(
    project_id: UUID,
    auth: AuthContext = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    """Get all variables available as analysis stubs."""
    try:
        project = await get_project(db, project_id, auth.db_user)
    except ProjectAccessError as e:
        return JSONResponse(status_code=404, content=error_response("NOT_FOUND", str(e)))

    if not project.dataset_metadata:
        return JSONResponse(status_code=400, content=error_response("NO_DATA", "No dataset uploaded"))

    stubs = [
        {"name": v["name"], "label": v.get("label", ""), "type": v.get("type", "")}
        for v in project.dataset_metadata.enriched_variables
    ]
    return success_response(stubs)
