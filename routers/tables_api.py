"""Generate Tables API — wizard-style tabulation that delegates to tabulation_builder."""

import logging
from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth_unified import AuthContext, require_user
from db.database import get_db
from db.models.export import TableTemplate
from schemas.exports import GenerateTablesConfig, TableTemplateCreate, TableTemplateOut
from services.project_service import ProjectAccessError, get_project
from shared.response import error_response, success_response

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/projects/{project_id}/tables", tags=["Generate Tables"])


@router.post("/preview")
async def preview_tables(
    project_id: UUID, config: GenerateTablesConfig,
    auth: AuthContext = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    """Dry-run: show plan without generating Excel."""
    try:
        await get_project(db, project_id, auth.db_user)
    except ProjectAccessError as e:
        return JSONResponse(status_code=404, content=error_response("NOT_FOUND", str(e)))

    from services.data_manager import get_project_data
    from services.table_wizard import generate_tables_preview
    try:
        data = await get_project_data(str(project_id))
    except Exception as e:
        return JSONResponse(status_code=400, content=error_response("NO_DATA", str(e)))

    preview = await generate_tables_preview(data, config.model_dump())
    return success_response(preview)


@router.post("/generate")
async def generate_tables(
    project_id: UUID, config: GenerateTablesConfig,
    auth: AuthContext = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    """Execute tabulation and return structured JSON results."""
    try:
        await get_project(db, project_id, auth.db_user)
    except ProjectAccessError as e:
        return JSONResponse(status_code=404, content=error_response("NOT_FOUND", str(e)))

    from services.data_manager import get_project_data
    from services.table_wizard import generate_tables_json
    try:
        data = await get_project_data(str(project_id))
    except Exception as e:
        return JSONResponse(status_code=400, content=error_response("NO_DATA", str(e)))

    try:
        result = await generate_tables_json(data, config.model_dump())
        return success_response(result)
    except Exception as e:
        logger.error("Generate tables failed: %s", e)
        return JSONResponse(status_code=500, content=error_response("GENERATION_FAILED", str(e)))


@router.post("/export")
async def export_tables(
    project_id: UUID, config: GenerateTablesConfig,
    auth: AuthContext = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    """Execute tabulation and return Excel file."""
    try:
        await get_project(db, project_id, auth.db_user)
    except ProjectAccessError as e:
        return JSONResponse(status_code=404, content=error_response("NOT_FOUND", str(e)))

    from services.data_manager import get_project_data
    from services.table_wizard import generate_tables_excel
    try:
        data = await get_project_data(str(project_id))
    except Exception as e:
        return JSONResponse(status_code=400, content=error_response("NO_DATA", str(e)))

    try:
        excel_bytes = await generate_tables_excel(data, config.model_dump())
        return Response(
            content=excel_bytes,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename=tabulation_{project_id}.xlsx"},
        )
    except Exception as e:
        logger.error("Export tables failed: %s", e)
        return JSONResponse(status_code=500, content=error_response("EXPORT_FAILED", str(e)))


# ─── Templates CRUD ──────────────────────────────────────────────────────


@router.post("/templates")
async def create_template(
    project_id: UUID, data: TableTemplateCreate,
    auth: AuthContext = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    try:
        await get_project(db, project_id, auth.db_user)
    except ProjectAccessError as e:
        return JSONResponse(status_code=404, content=error_response("NOT_FOUND", str(e)))

    template = TableTemplate(project_id=project_id, name=data.name, config=data.config)
    db.add(template)
    await db.flush()
    return success_response(TableTemplateOut.model_validate(template).model_dump(mode="json"))


@router.get("/templates")
async def list_templates(
    project_id: UUID,
    auth: AuthContext = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    try:
        await get_project(db, project_id, auth.db_user)
    except ProjectAccessError as e:
        return JSONResponse(status_code=404, content=error_response("NOT_FOUND", str(e)))

    result = await db.execute(
        select(TableTemplate).where(TableTemplate.project_id == project_id)
    )
    templates = result.scalars().all()
    return success_response([TableTemplateOut.model_validate(t).model_dump(mode="json") for t in templates])


@router.delete("/templates/{template_id}")
async def delete_template(
    project_id: UUID, template_id: UUID,
    auth: AuthContext = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    try:
        await get_project(db, project_id, auth.db_user)
    except ProjectAccessError as e:
        return JSONResponse(status_code=404, content=error_response("NOT_FOUND", str(e)))

    result = await db.execute(
        select(TableTemplate).where(TableTemplate.id == template_id, TableTemplate.project_id == project_id)
    )
    template = result.scalar_one_or_none()
    if not template:
        return JSONResponse(status_code=404, content=error_response("NOT_FOUND", "Template not found"))

    await db.delete(template)
    await db.flush()
    return success_response(None)
