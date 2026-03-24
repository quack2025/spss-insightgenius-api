"""POST /v1/files/upload — HTTP multipart upload for large files.

This endpoint solves the Claude.ai limitation where base64-encoded files
in MCP tool calls exceed output token limits for files > ~1MB.

Flow:
  1. User uploads file via HTTP POST (or via /upload web page)
  2. Server returns file_id
  3. User gives file_id to Claude
  4. Claude calls MCP tools with file_id (no base64 needed)

Uses the same Redis session store as MCP spss_upload_file.
"""

import json
import logging
import uuid

from fastapi import APIRouter, File, Header, HTTPException, Query, UploadFile

from auth import get_key_config
from config import get_settings
from middleware.processing import run_in_executor

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Files"])

# Supported formats
ALLOWED_EXTENSIONS = {"sav", "csv", "tsv", "xlsx", "xls"}


def _get_extension(filename: str) -> str:
    """Extract and validate file extension."""
    if not filename or "." not in filename:
        return ""
    return filename.rsplit(".", 1)[-1].lower()


@router.post(
    "/v1/files/upload",
    summary="Upload file for MCP session",
    description=(
        "Upload a .sav, .csv, .tsv, or .xlsx file via multipart/form-data. "
        "Returns a `file_id` valid for 30 minutes that can be used with any MCP tool "
        "or API endpoint. Designed for Claude.ai integration where base64 encoding "
        "exceeds token limits."
    ),
    responses={
        200: {"description": "File uploaded, session created"},
        401: {"description": "Invalid or missing API key"},
        413: {"description": "File exceeds plan size limit"},
        415: {"description": "Unsupported file format"},
        422: {"description": "File is corrupted or unreadable"},
    },
)
async def upload_file(
    file: UploadFile = File(..., description="Data file (.sav, .csv, .tsv, .xlsx, .xls)"),
    x_api_key: str | None = Header(None, alias="X-API-Key"),
    api_key: str | None = Query(None, description="API key (alternative to X-API-Key header)"),
):
    """Upload a data file and get a file_id for use with MCP tools."""

    # Auth — accept header or query param
    key_str = x_api_key or api_key
    if not key_str:
        raise HTTPException(401, {"error": "Missing API key. Pass X-API-Key header or ?api_key= query param."})

    try:
        key_config = get_key_config(key_str)
    except ValueError:
        raise HTTPException(401, {"error": "Invalid API key."})

    # Validate extension
    ext = _get_extension(file.filename or "")
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            415,
            {"error": f"Unsupported format '.{ext}'. Accepted: {', '.join('.' + e for e in sorted(ALLOWED_EXTENSIONS))}"},
        )

    # Read file
    content = await file.read()
    if not content:
        raise HTTPException(422, {"error": "Empty file."})

    # Validate size per plan
    settings = get_settings()
    max_bytes = settings.redis_max_file_size_mb * 1024 * 1024
    size_mb = len(content) / (1024 * 1024)
    if len(content) > max_bytes:
        raise HTTPException(
            413,
            {"error": f"File too large ({size_mb:.1f} MB). Maximum: {settings.redis_max_file_size_mb} MB for your plan."},
        )

    # Validate file can be loaded
    from routers.mcp_server import _load_data
    try:
        data = await run_in_executor(_load_data, content, ext, file.filename or "upload." + ext)
    except Exception as e:
        raise HTTPException(422, {"error": f"File is corrupted or unreadable: {e}"})

    # Store in Redis (same session store as MCP)
    from routers.mcp_server import _get_redis
    r = await _get_redis()
    if r is None:
        raise HTTPException(
            503,
            {"error": "File sessions require Redis. Contact support."},
        )

    file_id = str(uuid.uuid4())
    ttl = settings.spss_session_ttl_seconds
    n_cases = len(data.df)
    n_variables = len(data.df.columns)

    try:
        meta_info = json.dumps({
            "filename": file.filename,
            "format": ext,
            "n_cases": n_cases,
            "n_variables": n_variables,
            "size_bytes": len(content),
        })
        await r.set(f"spss:file:{file_id}", content, ex=ttl)
        await r.set(f"spss:meta:{file_id}", meta_info.encode(), ex=ttl)
        await r.aclose()
    except Exception as e:
        try:
            await r.aclose()
        except Exception:
            pass
        logger.error("Redis error storing upload: %s", e)
        raise HTTPException(503, {"error": "Failed to store file session. Try again."})

    logger.info(
        "[UPLOAD] key=%s file=%s size=%.1fMB cases=%d vars=%d file_id=%s",
        key_config.name, file.filename, size_mb, n_cases, n_variables, file_id,
    )

    return {
        "file_id": file_id,
        "filename": file.filename,
        "format": ext,
        "size_bytes": len(content),
        "n_cases": n_cases,
        "n_variables": n_variables,
        "session_ttl_seconds": ttl,
        "message": (
            f"File uploaded successfully. Use file_id='{file_id}' with any MCP tool or API endpoint. "
            f"Session expires after {ttl // 60} minutes of inactivity."
        ),
    }
