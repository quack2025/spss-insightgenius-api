"""Share Links API + Public Dashboard access."""
import secrets
import hashlib
import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth_unified import AuthContext, require_user
from db.database import get_db
from db.models.dashboard import ShareLink, Dashboard
from schemas.dashboards import ShareLinkCreate, ShareLinkOut
from services.project_service import ProjectAccessError, get_project
from shared.response import error_response, success_response

logger = logging.getLogger(__name__)

# Authenticated share link management
share_router = APIRouter(prefix="/v1/projects/{project_id}/share", tags=["Share"])

# Public dashboard access (no auth)
public_router = APIRouter(prefix="/v1/public", tags=["Public"])


@share_router.post("")
async def create_share_link(
    project_id: UUID, data: ShareLinkCreate,
    auth: AuthContext = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    try:
        await get_project(db, project_id, auth.db_user)
    except ProjectAccessError as e:
        return JSONResponse(status_code=404, content=error_response("NOT_FOUND", str(e)))

    token = secrets.token_urlsafe(32)
    password_hash = hashlib.sha256(data.password.encode()).hexdigest() if data.password else None
    expires_at = None
    if data.expires_in_hours:
        expires_at = datetime.now(timezone.utc) + timedelta(hours=data.expires_in_hours)

    link = ShareLink(
        project_id=project_id, token=token,
        password_hash=password_hash, expires_at=expires_at,
    )
    db.add(link)
    await db.flush()
    return success_response(ShareLinkOut.model_validate(link).model_dump(mode="json"))


@share_router.get("")
async def list_share_links(
    project_id: UUID, auth: AuthContext = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    try:
        await get_project(db, project_id, auth.db_user)
    except ProjectAccessError as e:
        return JSONResponse(status_code=404, content=error_response("NOT_FOUND", str(e)))

    result = await db.execute(select(ShareLink).where(ShareLink.project_id == project_id))
    links = result.scalars().all()
    return success_response([ShareLinkOut.model_validate(l).model_dump(mode="json") for l in links])


@share_router.delete("/{link_id}")
async def delete_share_link(
    project_id: UUID, link_id: UUID,
    auth: AuthContext = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    try:
        await get_project(db, project_id, auth.db_user)
    except ProjectAccessError as e:
        return JSONResponse(status_code=404, content=error_response("NOT_FOUND", str(e)))

    result = await db.execute(
        select(ShareLink).where(ShareLink.id == link_id, ShareLink.project_id == project_id)
    )
    link = result.scalar_one_or_none()
    if not link:
        return JSONResponse(status_code=404, content=error_response("NOT_FOUND", "Share link not found"))

    await db.delete(link)
    await db.flush()
    return success_response(None)


# ─── Public (no auth) ────────────────────────────────────────────────────


@public_router.get("/dashboards/{share_token}")
async def get_public_dashboard(share_token: str, db: AsyncSession = Depends(get_db)):
    """View a published dashboard via share token (no auth required)."""
    result = await db.execute(
        select(Dashboard).where(Dashboard.share_token == share_token, Dashboard.is_published == True)
    )
    dashboard = result.scalar_one_or_none()
    if not dashboard:
        return JSONResponse(status_code=404, content=error_response("NOT_FOUND", "Dashboard not found or not published"))

    return success_response({
        "name": dashboard.name,
        "widgets": dashboard.widgets,
        "filters": dashboard.filters,
    })
