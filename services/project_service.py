"""Project service — CRUD operations and access control.

All project operations require a db_user (from Supabase JWT auth).
"""

import logging
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from db.models.project import (
    DatasetMetadata,
    OwnerType,
    Project,
    ProjectFile,
    ProjectStatus,
)
from db.models.user import User
from schemas.projects import ProjectCreate, ProjectUpdate

logger = logging.getLogger(__name__)


class ProjectAccessError(Exception):
    """User does not have access to this project."""


async def create_project(db: AsyncSession, user: User, data: ProjectCreate) -> Project:
    """Create a new project owned by the user."""
    project = Project(
        name=data.name,
        description=data.description,
        owner_type=OwnerType.USER,
        owner_id=user.id,
        status=ProjectStatus.PROCESSING,
        study_objective=data.study_objective,
        country=data.country,
        industry=data.industry,
        target_audience=data.target_audience,
        brands=data.brands,
        methodology=data.methodology,
        study_date=data.study_date,
        is_tracking=data.is_tracking,
        report_language=data.report_language,
        low_base_threshold=data.low_base_threshold,
    )
    db.add(project)
    await db.flush()
    logger.info("Created project %s for user %s", project.id, user.id)
    return project


async def list_projects(db: AsyncSession, user: User) -> list[dict]:
    """List all projects accessible by the user (owned + team)."""
    stmt = (
        select(
            Project.id,
            Project.name,
            Project.description,
            Project.status,
            Project.created_at,
            func.count(ProjectFile.id).label("file_count"),
        )
        .outerjoin(ProjectFile, ProjectFile.project_id == Project.id)
        .where(Project.owner_id == user.id, Project.owner_type == OwnerType.USER)
        .group_by(Project.id)
        .order_by(Project.created_at.desc())
    )
    result = await db.execute(stmt)
    rows = result.all()

    projects = []
    for row in rows:
        projects.append({
            "id": row.id,
            "name": row.name,
            "description": row.description,
            "status": row.status.value if hasattr(row.status, "value") else row.status,
            "created_at": row.created_at,
            "file_count": row.file_count,
        })
    return projects


async def get_project(db: AsyncSession, project_id: uuid.UUID, user: User) -> Project:
    """Get a project by ID with access check. Loads files and metadata."""
    stmt = (
        select(Project)
        .options(
            selectinload(Project.files),
            selectinload(Project.dataset_metadata),
        )
        .where(Project.id == project_id)
    )
    result = await db.execute(stmt)
    project = result.scalar_one_or_none()

    if project is None:
        raise ProjectAccessError("Project not found")

    _check_access(project, user)
    return project


async def update_project(
    db: AsyncSession, project_id: uuid.UUID, user: User, data: ProjectUpdate
) -> Project:
    """Update project fields."""
    project = await get_project(db, project_id, user)

    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(project, field, value)

    await db.flush()
    return project


async def delete_project(db: AsyncSession, project_id: uuid.UUID, user: User) -> None:
    """Delete a project and all related data."""
    project = await get_project(db, project_id, user)
    await db.delete(project)
    await db.flush()
    logger.info("Deleted project %s", project_id)


def _check_access(project: Project, user: User) -> None:
    """Verify user can access this project."""
    if project.owner_type == OwnerType.USER:
        if project.owner_id != user.id:
            raise ProjectAccessError("Access denied")
    # TODO: Team access check in Phase 6
