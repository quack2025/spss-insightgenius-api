"""Library endpoints: persistent file storage with metadata indexing."""

import logging

from fastapi import APIRouter, File, Form, Query, UploadFile
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Library"])


@router.post("/v1/library/upload", summary="Upload file to persistent library")
async def library_upload(
    file: UploadFile = File(...),
    description: str = Form(""),
    tags: str = Form(""),
    user_id: str = Form("demo"),
):
    """Upload a file to the persistent library. Returns library_id + file_id (Redis session)."""
    from services.library_service import LibraryService

    file_bytes = await file.read()
    filename = file.filename or "upload.sav"

    try:
        svc = LibraryService()
        result = await svc.upload_file(file_bytes, filename, user_id=user_id)

        # Also load into Redis for immediate analysis
        file_id = await svc.load_to_redis(result["library_id"])

        return {
            "success": True,
            "data": {
                **result,
                "file_id": file_id or result["library_id"],
                "description": description,
            },
        }
    except Exception as e:
        logger.error("Library upload failed: %s", e, exc_info=True)
        return JSONResponse(status_code=500, content={
            "success": False,
            "error": {"code": "LIBRARY_ERROR", "message": str(e)},
        })


@router.get("/v1/library/files", summary="List all files in library")
async def library_list(user_id: str = Query("demo")):
    """List all files for a user with metadata summary."""
    from services.library_service import LibraryService

    try:
        svc = LibraryService()
        files = await svc.list_files(user_id)
        return {"success": True, "data": {"files": files, "total": len(files)}}
    except Exception as e:
        return JSONResponse(status_code=500, content={
            "success": False,
            "error": {"code": "LIBRARY_ERROR", "message": str(e)},
        })


@router.get("/v1/library/{library_id}", summary="Get file metadata")
async def library_get(library_id: str):
    """Get metadata for a specific library file."""
    from services.library_service import LibraryService

    try:
        svc = LibraryService()
        meta = await svc.get_file_metadata(library_id)
        if not meta:
            return JSONResponse(status_code=404, content={
                "success": False,
                "error": {"code": "NOT_FOUND", "message": f"File {library_id} not found"},
            })
        return {"success": True, "data": meta}
    except Exception as e:
        return JSONResponse(status_code=500, content={
            "success": False,
            "error": {"code": "LIBRARY_ERROR", "message": str(e)},
        })


@router.get("/v1/library/{library_id}/variables", summary="Get file variables")
async def library_variables(library_id: str):
    """Get all variables for a library file."""
    from services.library_service import LibraryService

    try:
        svc = LibraryService()
        variables = await svc.get_file_variables(library_id)
        return {"success": True, "data": {"variables": variables, "total": len(variables)}}
    except Exception as e:
        return JSONResponse(status_code=500, content={
            "success": False,
            "error": {"code": "LIBRARY_ERROR", "message": str(e)},
        })


@router.post("/v1/library/{library_id}/load", summary="Load library file into active session")
async def library_load(library_id: str):
    """Load a library file into Redis for active analysis. Returns file_id."""
    from services.library_service import LibraryService

    try:
        svc = LibraryService()
        file_id = await svc.load_to_redis(library_id)
        if not file_id:
            return JSONResponse(status_code=404, content={
                "success": False,
                "error": {"code": "NOT_FOUND", "message": "File not found or Redis unavailable"},
            })
        return {"success": True, "data": {"file_id": file_id, "library_id": library_id}}
    except Exception as e:
        return JSONResponse(status_code=500, content={
            "success": False,
            "error": {"code": "LIBRARY_ERROR", "message": str(e)},
        })


@router.patch("/v1/library/{library_id}", summary="Update file metadata (rename, tags, description)")
async def library_update(library_id: str, display_name: str = Form(None), description: str = Form(None), tags: str = Form(None)):
    """Update file display name, description, or tags."""
    from services.library_service import LibraryService
    import httpx

    try:
        svc = LibraryService()
        updates = {}
        if display_name is not None:
            updates["display_name"] = display_name
        if description is not None:
            updates["description"] = description
        if tags is not None:
            updates["tags"] = [t.strip() for t in tags.split(",") if t.strip()]

        if not updates:
            return JSONResponse(status_code=400, content={"success": False, "error": {"message": "No fields to update"}})

        async with httpx.AsyncClient() as client:
            resp = await client.patch(
                f"{svc.rest_url}/library_files?id=eq.{library_id}",
                headers={**svc.headers, "Content-Type": "application/json", "Prefer": "return=representation"},
                json=updates,
            )
            if resp.status_code == 200:
                data = resp.json()
                return {"success": True, "data": data[0] if data else {}}
            return JSONResponse(status_code=resp.status_code, content={"success": False, "error": {"message": resp.text[:200]}})
    except Exception as e:
        return JSONResponse(status_code=500, content={"success": False, "error": {"code": "LIBRARY_ERROR", "message": str(e)}})


@router.delete("/v1/library/{library_id}", summary="Delete file from library")
async def library_delete(library_id: str):
    """Delete a file from the library (storage + metadata)."""
    from services.library_service import LibraryService

    try:
        svc = LibraryService()
        deleted = await svc.delete_file(library_id)
        if not deleted:
            return JSONResponse(status_code=404, content={
                "success": False,
                "error": {"code": "NOT_FOUND", "message": "File not found"},
            })
        return {"success": True, "message": "File deleted"}
    except Exception as e:
        return JSONResponse(status_code=500, content={
            "success": False,
            "error": {"code": "LIBRARY_ERROR", "message": str(e)},
        })


@router.get("/v1/library/search/files", summary="Search across library")
async def library_search(q: str = Query(...), user_id: str = Query("demo")):
    """Search files and variables by keyword."""
    from services.library_service import LibraryService

    try:
        svc = LibraryService()
        results = await svc.search_files(user_id, q)
        return {"success": True, "data": {"results": results, "total": len(results)}}
    except Exception as e:
        return JSONResponse(status_code=500, content={
            "success": False,
            "error": {"code": "LIBRARY_ERROR", "message": str(e)},
        })
