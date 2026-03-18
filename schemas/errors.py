"""Error response models — the API error contract."""

from enum import Enum
from typing import Literal

from pydantic import BaseModel


class ErrorCode(str, Enum):
    INVALID_FILE_FORMAT = "INVALID_FILE_FORMAT"
    FILE_TOO_LARGE = "FILE_TOO_LARGE"
    VARIABLE_NOT_FOUND = "VARIABLE_NOT_FOUND"
    INVALID_TICKET = "INVALID_TICKET"
    INVALID_OPERATIONS = "INVALID_OPERATIONS"
    RATE_LIMIT_EXCEEDED = "RATE_LIMIT_EXCEEDED"
    UNAUTHORIZED = "UNAUTHORIZED"
    FORBIDDEN = "FORBIDDEN"
    PROCESSING_FAILED = "PROCESSING_FAILED"
    TIMEOUT = "TIMEOUT"
    VALIDATION_ERROR = "VALIDATION_ERROR"


class ErrorDetail(BaseModel):
    code: str
    message: str
    param: str | None = None


class ErrorResponse(BaseModel):
    success: Literal[False] = False
    error: ErrorDetail
    request_id: str = ""
