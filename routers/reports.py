"""Reports API — AI-generated multi-analysis reports."""

import asyncio
import logging
from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth_unified import AuthContext, require_user
from db.database import get_db
from db.models.export import Report, ReportStatus
from schemas.exports import ReportCreate, ReportOut, ReportDetailOut
from services.project_service import ProjectAccessError, get_project
from shared.response import error_response, success_response

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/projects/{project_id}/reports", tags=["Reports"])

REPORT_TIMEOUT_SECONDS = 120


@router.post("")
async def create_report(
    project_id: UUID, data: ReportCreate,
    auth: AuthContext = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    """Generate a multi-analysis report with AI narrative."""
    try:
        project = await get_project(db, project_id, auth.db_user)
    except ProjectAccessError as e:
        return JSONResponse(status_code=404, content=error_response("NOT_FOUND", str(e)))

    if not project.dataset_metadata:
        return JSONResponse(status_code=400, content=error_response("NO_DATA", "No dataset uploaded"))

    # Create report record
    report = Report(
        project_id=project_id,
        title=data.title,
        status=ReportStatus.GENERATING,
    )
    db.add(report)
    await db.flush()

    # Generate report (with timeout)
    from services.data_manager import get_project_data
    from services.report_generator import generate_report

    try:
        spss_data = await get_project_data(str(project_id))
        variables_info = project.dataset_metadata.enriched_variables

        result = await asyncio.wait_for(
            generate_report(
                data=spss_data,
                variables_info=variables_info,
                language=project.report_language,
                depth=data.depth,
            ),
            timeout=REPORT_TIMEOUT_SECONDS,
        )

        report.status = ReportStatus.READY
        report.content = result
        report.progress = 100
        await db.flush()

        return success_response(ReportDetailOut.model_validate(report).model_dump(mode="json"))

    except asyncio.TimeoutError:
        report.status = ReportStatus.FAILED
        report.error_message = f"Report generation exceeded {REPORT_TIMEOUT_SECONDS}s timeout"
        await db.flush()
        return JSONResponse(status_code=504, content=error_response("TIMEOUT", report.error_message))

    except Exception as e:
        report.status = ReportStatus.FAILED
        report.error_message = str(e)[:500]
        await db.flush()
        logger.error("Report generation failed: %s", e)
        return JSONResponse(status_code=500, content=error_response("GENERATION_FAILED", str(e)))


@router.get("")
async def list_reports(
    project_id: UUID,
    auth: AuthContext = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    try:
        await get_project(db, project_id, auth.db_user)
    except ProjectAccessError as e:
        return JSONResponse(status_code=404, content=error_response("NOT_FOUND", str(e)))

    result = await db.execute(
        select(Report).where(Report.project_id == project_id).order_by(Report.created_at.desc())
    )
    reports = result.scalars().all()
    return success_response([ReportOut.model_validate(r).model_dump(mode="json") for r in reports])


@router.get("/{report_id}")
async def get_report(
    project_id: UUID, report_id: UUID,
    auth: AuthContext = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    try:
        await get_project(db, project_id, auth.db_user)
    except ProjectAccessError as e:
        return JSONResponse(status_code=404, content=error_response("NOT_FOUND", str(e)))

    result = await db.execute(
        select(Report).where(Report.id == report_id, Report.project_id == project_id)
    )
    report = result.scalar_one_or_none()
    if not report:
        return JSONResponse(status_code=404, content=error_response("NOT_FOUND", "Report not found"))

    return success_response(ReportDetailOut.model_validate(report).model_dump(mode="json"))
