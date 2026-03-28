"""Shared validation functions — single source of truth."""

import math
from typing import Any

from fastapi import HTTPException, UploadFile

ALLOWED_EXTENSIONS = {"sav", "por", "zsav", "csv", "tsv", "xlsx", "xls"}
SPSS_EXTENSIONS = {"sav", "por", "zsav"}


def validate_upload(file: UploadFile, allowed: set[str] | None = None) -> None:
    """Validate an uploaded file has an acceptable extension.

    Args:
        file: The uploaded file
        allowed: Set of allowed extensions. Defaults to SPSS_EXTENSIONS.
    """
    exts = allowed or SPSS_EXTENSIONS
    if not file.filename:
        raise HTTPException(400, detail={
            "code": "INVALID_FILE_FORMAT",
            "message": "No filename provided",
        })
    ext = file.filename.lower().rsplit(".", 1)[-1] if "." in file.filename else ""
    if ext not in exts:
        raise HTTPException(400, detail={
            "code": "INVALID_FILE_FORMAT",
            "message": f"Unsupported format '.{ext}'. Accepted: {', '.join('.' + e for e in sorted(exts))}",
        })


def clean_numeric(val: Any) -> Any:
    """Replace NaN/Inf with None, round floats to 4 decimals."""
    if isinstance(val, float):
        if math.isnan(val) or math.isinf(val):
            return None
        return round(val, 4)
    return val
