"""Standard API response envelope — consistent shape for all endpoints."""

import time
import uuid
from typing import Any


def success_response(
    data: Any,
    *,
    processing_time_ms: int | None = None,
    meta: dict | None = None,
) -> dict:
    """Standard success response envelope.

    {
        "success": true,
        "data": { ... },
        "meta": { "request_id": "...", "processing_time_ms": 42 }
    }
    """
    resp = {
        "success": True,
        "data": data,
    }
    resp_meta = {"request_id": str(uuid.uuid4())[:8]}
    if processing_time_ms is not None:
        resp_meta["processing_time_ms"] = processing_time_ms
    if meta:
        resp_meta.update(meta)
    resp["meta"] = resp_meta
    return resp


def error_response(
    code: str,
    message: str,
    *,
    status_code: int = 400,
    doc_url: str | None = None,
) -> dict:
    """Standard error response body (use with JSONResponse(status_code=..., content=...)).

    {
        "success": false,
        "error": {
            "code": "VALIDATION_ERROR",
            "message": "Variable 'Q99' not found",
            "doc_url": "https://spss.insightgenius.io/docs#errors"
        }
    }
    """
    err = {"code": code, "message": message}
    if doc_url:
        err["doc_url"] = doc_url
    return {
        "success": False,
        "error": err,
    }
