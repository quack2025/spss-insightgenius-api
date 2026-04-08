"""Projects API — CRUD + file upload.

All endpoints require Supabase JWT auth (platform users).
Follows the standard response envelope: {"success": true, "data": {...}, "meta": {...}}
"""

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from auth_unified import AuthContext, require_user
from db.database import get_db
from db.models.project import FileType, ProjectFile, ProjectStatus
from schemas.projects import (
    FileOut,
    FileUploadOut,
    ProjectCreate,
    ProjectListOut,
    ProjectOut,
    ProjectUpdate,
    DatasetMetadataOut,
    VariableInfo,
)
from services.project_service import (
    ProjectAccessError,
    create_project,
    delete_project,
    get_project,
    list_projects,
    update_project,
)
from shared.response import error_response, success_response

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/projects", tags=["Projects"])

# File type mapping from extension
EXTENSION_TO_TYPE = {
    ".sav": FileType.SPSS_DATA,
    ".por": FileType.SPSS_DATA,
    ".zsav": FileType.SPSS_DATA,
    ".csv": FileType.CSV_DATA,
    ".xlsx": FileType.EXCEL_DATA,
    ".xls": FileType.EXCEL_DATA,
    ".pdf": FileType.QUESTIONNAIRE_PDF,
}

MAX_FILE_SIZE = 200 * 1024 * 1024  # 200 MB


# ─── CRUD ─────────────────────────────────────────────────────────────────


@router.post("")
async def create_project_endpoint(
    data: ProjectCreate,
    auth: AuthContext = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new project."""
    project = await create_project(db, auth.db_user, data)
    return success_response({
        "id": str(project.id),
        "name": project.name,
        "status": project.status.value,
        "created_at": project.created_at.isoformat(),
    })


@router.get("")
async def list_projects_endpoint(
    auth: AuthContext = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    """List all projects for the authenticated user."""
    projects = await list_projects(db, auth.db_user)
    return success_response(projects, meta={"total": len(projects)})


@router.get("/{project_id}")
async def get_project_endpoint(
    project_id: UUID,
    auth: AuthContext = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    """Get project details with files and metadata."""
    try:
        project = await get_project(db, project_id, auth.db_user)
    except ProjectAccessError as e:
        return JSONResponse(status_code=404, content=error_response("NOT_FOUND", str(e)))

    # Build response
    files = [
        FileOut(
            id=f.id,
            file_type=f.file_type.value,
            original_name=f.original_name,
            size_bytes=f.size_bytes,
            uploaded_at=f.uploaded_at,
        )
        for f in (project.files or [])
    ]

    metadata = None
    if project.dataset_metadata:
        dm = project.dataset_metadata
        metadata = DatasetMetadataOut(
            n_cases=dm.n_cases,
            n_variables=dm.n_variables,
            variables=[
                VariableInfo(
                    name=v.get("name", ""),
                    label=v.get("label", ""),
                    type=v.get("type", ""),
                    n_values=len(v.get("value_labels", {}) or {}),
                    values=v.get("value_labels"),
                )
                for v in (dm.enriched_variables or [])
            ],
        )

    out = ProjectOut(
        id=project.id,
        name=project.name,
        description=project.description,
        status=project.status.value,
        owner_type=project.owner_type.value,
        created_at=project.created_at,
        updated_at=project.updated_at,
        study_objective=project.study_objective,
        country=project.country,
        industry=project.industry,
        target_audience=project.target_audience,
        brands=project.brands,
        methodology=project.methodology,
        study_date=project.study_date,
        is_tracking=project.is_tracking,
        report_language=project.report_language,
        low_base_threshold=project.low_base_threshold,
        files=files,
        metadata=metadata,
    )
    return success_response(out.model_dump(mode="json"))


@router.patch("/{project_id}")
async def update_project_endpoint(
    project_id: UUID,
    data: ProjectUpdate,
    auth: AuthContext = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    """Update project fields."""
    try:
        project = await update_project(db, project_id, auth.db_user, data)
    except ProjectAccessError as e:
        return JSONResponse(status_code=404, content=error_response("NOT_FOUND", str(e)))

    return success_response({
        "id": str(project.id),
        "name": project.name,
        "status": project.status.value,
    })


@router.delete("/{project_id}")
async def delete_project_endpoint(
    project_id: UUID,
    auth: AuthContext = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a project and all related data."""
    try:
        await delete_project(db, project_id, auth.db_user)
    except ProjectAccessError as e:
        return JSONResponse(status_code=404, content=error_response("NOT_FOUND", str(e)))

    return success_response(None)


# ─── File Upload ──────────────────────────────────────────────────────────


@router.post("/{project_id}/files/upload")
async def upload_file_endpoint(
    project_id: UUID,
    file: UploadFile = File(...),
    file_type: str | None = Query(None, description="Override file type detection"),
    auth: AuthContext = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    """Upload a data file to a project.

    Supports SPSS (.sav), CSV (.csv), Excel (.xlsx).
    Automatically extracts metadata from SPSS files.
    """
    try:
        project = await get_project(db, project_id, auth.db_user)
    except ProjectAccessError as e:
        return JSONResponse(status_code=404, content=error_response("NOT_FOUND", str(e)))

    # Determine file type
    filename = file.filename or "unknown"
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    detected_type = EXTENSION_TO_TYPE.get(ext)

    if file_type:
        try:
            detected_type = FileType(file_type)
        except ValueError:
            return JSONResponse(
                status_code=400,
                content=error_response("INVALID_FILE_TYPE", f"Unknown file type: {file_type}"),
            )

    if detected_type is None:
        return JSONResponse(
            status_code=400,
            content=error_response(
                "UNSUPPORTED_FORMAT",
                f"Unsupported file extension: {ext}. Use .sav, .csv, .xlsx, or .pdf",
            ),
        )

    # Read file with size limit
    file_bytes = await file.read()
    if len(file_bytes) > MAX_FILE_SIZE:
        return JSONResponse(
            status_code=413,
            content=error_response("FILE_TOO_LARGE", f"Max file size is {MAX_FILE_SIZE // (1024*1024)} MB"),
        )

    # Store file record (storage_path is placeholder — Supabase Storage in later iteration)
    file_record = ProjectFile(
        project_id=project.id,
        file_type=detected_type,
        storage_path=f"projects/{project.id}/{filename}",
        original_name=filename,
        size_bytes=len(file_bytes),
    )
    db.add(file_record)
    await db.flush()

    # Extract metadata for data files
    n_cases = None
    n_variables = None

    if detected_type == FileType.SPSS_DATA:
        try:
            from services.metadata_extractor import extract_and_store_metadata
            dataset_meta = await extract_and_store_metadata(db, project, file_record, file_bytes)
            n_cases = dataset_meta.n_cases
            n_variables = dataset_meta.n_variables
        except Exception as e:
            logger.warning("Metadata extraction failed for %s: %s", filename, e)
            # Project status already set to ERROR by extract_and_store_metadata

    # Also store in Redis for immediate analysis access (reuse existing session system)
    try:
        from shared.file_resolver import store_file_session
        file_id_str = str(file_record.id)
        await _store_in_redis(file_id_str, file_bytes, filename)
    except Exception as e:
        logger.debug("Redis file cache skipped: %s", e)

    return success_response(
        FileUploadOut(
            file_id=file_record.id,
            original_name=filename,
            size_bytes=len(file_bytes),
            file_type=detected_type.value,
            n_cases=n_cases,
            n_variables=n_variables,
        ).model_dump(mode="json")
    )


@router.get("/{project_id}/files")
async def list_files_endpoint(
    project_id: UUID,
    auth: AuthContext = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    """List files in a project."""
    try:
        project = await get_project(db, project_id, auth.db_user)
    except ProjectAccessError as e:
        return JSONResponse(status_code=404, content=error_response("NOT_FOUND", str(e)))

    files = [
        FileOut(
            id=f.id,
            file_type=f.file_type.value,
            original_name=f.original_name,
            size_bytes=f.size_bytes,
            uploaded_at=f.uploaded_at,
        ).model_dump(mode="json")
        for f in (project.files or [])
    ]
    return success_response(files)


@router.delete("/{project_id}/files/{file_id}")
async def delete_file_endpoint(
    project_id: UUID,
    file_id: UUID,
    auth: AuthContext = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a file from a project."""
    try:
        project = await get_project(db, project_id, auth.db_user)
    except ProjectAccessError as e:
        return JSONResponse(status_code=404, content=error_response("NOT_FOUND", str(e)))

    target = None
    for f in (project.files or []):
        if f.id == file_id:
            target = f
            break

    if target is None:
        return JSONResponse(status_code=404, content=error_response("NOT_FOUND", "File not found"))

    await db.delete(target)
    await db.flush()
    return success_response(None)


# ─── Helpers ──────────────────────────────────────────────────────────────


async def _store_in_redis(file_id: str, file_bytes: bytes, filename: str) -> None:
    """Store file bytes in Redis for immediate analysis access."""
    import redis.asyncio as aioredis
    from config import get_settings

    settings = get_settings()
    if not settings.redis_url:
        return

    r = aioredis.from_url(settings.redis_url)
    try:
        key = f"spss_session:{file_id}"
        import json
        session_data = json.dumps({
            "filename": filename,
            "size_bytes": len(file_bytes),
        })
        await r.set(f"{key}:meta", session_data, ex=settings.spss_session_ttl_seconds)
        await r.set(f"{key}:data", file_bytes, ex=settings.spss_session_ttl_seconds)
    finally:
        await r.aclose()
