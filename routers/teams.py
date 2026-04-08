"""Teams API — CRUD + member management."""
import logging
from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from auth_unified import AuthContext, require_user
from db.database import get_db
from db.models.team import Team, TeamMember, TeamRole
from db.models.user import User
from schemas.teams import TeamCreate, TeamUpdate, MemberAdd, TeamOut, MemberOut
from shared.response import error_response, success_response

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/teams", tags=["Teams"])


@router.post("")
async def create_team(
    data: TeamCreate, auth: AuthContext = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    team = Team(owner_id=auth.db_user.id, name=data.name, description=data.description)
    db.add(team)
    await db.flush()
    # Add owner as member
    member = TeamMember(team_id=team.id, user_id=auth.db_user.id, role=TeamRole.OWNER)
    db.add(member)
    await db.flush()
    return success_response({"id": str(team.id), "name": team.name})


@router.get("")
async def list_teams(auth: AuthContext = Depends(require_user), db: AsyncSession = Depends(get_db)):
    stmt = (
        select(Team.id, Team.name, Team.description, Team.created_at,
               func.count(TeamMember.id).label("member_count"))
        .join(TeamMember, TeamMember.team_id == Team.id)
        .where(TeamMember.user_id == auth.db_user.id)
        .group_by(Team.id)
    )
    result = await db.execute(stmt)
    teams = [{"id": str(r.id), "name": r.name, "description": r.description,
              "created_at": r.created_at.isoformat(), "member_count": r.member_count}
             for r in result.all()]
    return success_response(teams)


@router.get("/{team_id}")
async def get_team(team_id: UUID, auth: AuthContext = Depends(require_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Team).where(Team.id == team_id))
    team = result.scalar_one_or_none()
    if not team:
        return JSONResponse(status_code=404, content=error_response("NOT_FOUND", "Team not found"))

    # Check membership
    mem = await db.execute(
        select(TeamMember).where(TeamMember.team_id == team_id, TeamMember.user_id == auth.db_user.id)
    )
    if not mem.scalar_one_or_none():
        return JSONResponse(status_code=403, content=error_response("FORBIDDEN", "Not a team member"))

    # Get members
    members_result = await db.execute(select(TeamMember).where(TeamMember.team_id == team_id))
    members = [{"user_id": str(m.user_id), "role": m.role.value} for m in members_result.scalars().all()]

    return success_response({
        "id": str(team.id), "name": team.name, "description": team.description,
        "members": members, "created_at": team.created_at.isoformat(),
    })


@router.patch("/{team_id}")
async def update_team(
    team_id: UUID, data: TeamUpdate,
    auth: AuthContext = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Team).where(Team.id == team_id, Team.owner_id == auth.db_user.id))
    team = result.scalar_one_or_none()
    if not team:
        return JSONResponse(status_code=404, content=error_response("NOT_FOUND", "Team not found or not owner"))
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(team, field, value)
    await db.flush()
    return success_response({"id": str(team.id), "name": team.name})


@router.delete("/{team_id}")
async def delete_team(team_id: UUID, auth: AuthContext = Depends(require_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Team).where(Team.id == team_id, Team.owner_id == auth.db_user.id))
    team = result.scalar_one_or_none()
    if not team:
        return JSONResponse(status_code=404, content=error_response("NOT_FOUND", "Team not found or not owner"))
    await db.delete(team)
    await db.flush()
    return success_response(None)


@router.post("/{team_id}/members")
async def add_member(
    team_id: UUID, data: MemberAdd,
    auth: AuthContext = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    # Verify team ownership
    result = await db.execute(select(Team).where(Team.id == team_id, Team.owner_id == auth.db_user.id))
    if not result.scalar_one_or_none():
        return JSONResponse(status_code=403, content=error_response("FORBIDDEN", "Only owner can add members"))

    # Find user by email
    user_result = await db.execute(select(User).where(User.email == data.email))
    user = user_result.scalar_one_or_none()
    if not user:
        return JSONResponse(status_code=404, content=error_response("NOT_FOUND", f"User {data.email} not found"))

    member = TeamMember(team_id=team_id, user_id=user.id, role=TeamRole(data.role))
    db.add(member)
    await db.flush()
    return success_response({"user_id": str(user.id), "role": data.role})


@router.delete("/{team_id}/members/{user_id}")
async def remove_member(
    team_id: UUID, user_id: UUID,
    auth: AuthContext = Depends(require_user), db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Team).where(Team.id == team_id, Team.owner_id == auth.db_user.id))
    if not result.scalar_one_or_none():
        return JSONResponse(status_code=403, content=error_response("FORBIDDEN", "Only owner can remove members"))

    mem_result = await db.execute(
        select(TeamMember).where(TeamMember.team_id == team_id, TeamMember.user_id == user_id)
    )
    member = mem_result.scalar_one_or_none()
    if not member:
        return JSONResponse(status_code=404, content=error_response("NOT_FOUND", "Member not found"))

    await db.delete(member)
    await db.flush()
    return success_response(None)
