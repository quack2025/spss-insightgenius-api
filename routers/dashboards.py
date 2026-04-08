"""Dashboards API — CRUD + publish + widgets."""
import secrets
import logging
from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth_unified import AuthContext, require_user
from db.database import get_db
from db.models.dashboard import Dashboard
from schemas.dashboards import DashboardCreate, DashboardUpdate, DashboardOut, WidgetAdd
from services.project_service import ProjectAccessError, get_project
from shared.response import error_response, success_response

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/projects/{project_id}/dashboards", tags=["Dashboards"])


@router.post("")
async def create_dashboard(
    project_id: UUID, data: DashboardCreate,
    auth: AuthContext = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    try:
        await get_project(db, project_id, auth.db_user)
    except ProjectAccessError as e:
        return JSONResponse(status_code=404, content=error_response("NOT_FOUND", str(e)))

    dashboard = Dashboard(
        project_id=project_id, name=data.name,
        description=data.description, widgets=data.widgets,
    )
    db.add(dashboard)
    await db.flush()
    return success_response(DashboardOut.model_validate(dashboard).model_dump(mode="json"))


@router.get("")
async def list_dashboards(
    project_id: UUID, auth: AuthContext = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    try:
        await get_project(db, project_id, auth.db_user)
    except ProjectAccessError as e:
        return JSONResponse(status_code=404, content=error_response("NOT_FOUND", str(e)))

    result = await db.execute(select(Dashboard).where(Dashboard.project_id == project_id))
    dashboards = result.scalars().all()
    return success_response([DashboardOut.model_validate(d).model_dump(mode="json") for d in dashboards])


@router.get("/{dashboard_id}")
async def get_dashboard(
    project_id: UUID, dashboard_id: UUID,
    auth: AuthContext = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    try:
        await get_project(db, project_id, auth.db_user)
    except ProjectAccessError as e:
        return JSONResponse(status_code=404, content=error_response("NOT_FOUND", str(e)))

    result = await db.execute(
        select(Dashboard).where(Dashboard.id == dashboard_id, Dashboard.project_id == project_id)
    )
    dashboard = result.scalar_one_or_none()
    if not dashboard:
        return JSONResponse(status_code=404, content=error_response("NOT_FOUND", "Dashboard not found"))
    return success_response(DashboardOut.model_validate(dashboard).model_dump(mode="json"))


@router.put("/{dashboard_id}")
async def update_dashboard(
    project_id: UUID, dashboard_id: UUID, data: DashboardUpdate,
    auth: AuthContext = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    try:
        await get_project(db, project_id, auth.db_user)
    except ProjectAccessError as e:
        return JSONResponse(status_code=404, content=error_response("NOT_FOUND", str(e)))

    result = await db.execute(
        select(Dashboard).where(Dashboard.id == dashboard_id, Dashboard.project_id == project_id)
    )
    dashboard = result.scalar_one_or_none()
    if not dashboard:
        return JSONResponse(status_code=404, content=error_response("NOT_FOUND", "Dashboard not found"))

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(dashboard, field, value)
    await db.flush()
    return success_response(DashboardOut.model_validate(dashboard).model_dump(mode="json"))


@router.delete("/{dashboard_id}")
async def delete_dashboard(
    project_id: UUID, dashboard_id: UUID,
    auth: AuthContext = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    try:
        await get_project(db, project_id, auth.db_user)
    except ProjectAccessError as e:
        return JSONResponse(status_code=404, content=error_response("NOT_FOUND", str(e)))

    result = await db.execute(
        select(Dashboard).where(Dashboard.id == dashboard_id, Dashboard.project_id == project_id)
    )
    dashboard = result.scalar_one_or_none()
    if not dashboard:
        return JSONResponse(status_code=404, content=error_response("NOT_FOUND", "Dashboard not found"))

    await db.delete(dashboard)
    await db.flush()
    return success_response(None)


@router.post("/{dashboard_id}/publish")
async def publish_dashboard(
    project_id: UUID, dashboard_id: UUID,
    auth: AuthContext = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    try:
        await get_project(db, project_id, auth.db_user)
    except ProjectAccessError as e:
        return JSONResponse(status_code=404, content=error_response("NOT_FOUND", str(e)))

    result = await db.execute(
        select(Dashboard).where(Dashboard.id == dashboard_id, Dashboard.project_id == project_id)
    )
    dashboard = result.scalar_one_or_none()
    if not dashboard:
        return JSONResponse(status_code=404, content=error_response("NOT_FOUND", "Dashboard not found"))

    dashboard.is_published = True
    if not dashboard.share_token:
        dashboard.share_token = secrets.token_urlsafe(32)
    await db.flush()

    return success_response({
        "share_token": dashboard.share_token,
        "share_url": f"/v1/public/dashboards/{dashboard.share_token}",
    })


@router.post("/{dashboard_id}/widgets")
async def add_widget(
    project_id: UUID, dashboard_id: UUID, data: WidgetAdd,
    auth: AuthContext = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    try:
        await get_project(db, project_id, auth.db_user)
    except ProjectAccessError as e:
        return JSONResponse(status_code=404, content=error_response("NOT_FOUND", str(e)))

    result = await db.execute(
        select(Dashboard).where(Dashboard.id == dashboard_id, Dashboard.project_id == project_id)
    )
    dashboard = result.scalar_one_or_none()
    if not dashboard:
        return JSONResponse(status_code=404, content=error_response("NOT_FOUND", "Dashboard not found"))

    widgets = list(dashboard.widgets or [])
    widgets.append(data.model_dump())
    dashboard.widgets = widgets
    await db.flush()
    return success_response({"widget_count": len(widgets)})
