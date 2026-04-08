"""Pydantic schemas for Projects API — request and response models.

All responses follow the standard envelope:
  {"success": true, "data": {...}, "meta": {...}}
"""

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, Field


# ─── Request schemas ──────────────────────────────────────────────────────


class ProjectCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    study_objective: str | None = None
    country: str | None = None
    industry: str | None = None
    target_audience: str | None = None
    brands: list[str] | None = None
    methodology: str | None = None
    study_date: date | None = None
    is_tracking: bool = False
    report_language: str = "en"
    low_base_threshold: int = 20


class ProjectUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None
    study_objective: str | None = None
    country: str | None = None
    industry: str | None = None
    target_audience: str | None = None
    brands: list[str] | None = None
    methodology: str | None = None
    study_date: date | None = None
    is_tracking: bool | None = None
    report_language: str | None = None
    low_base_threshold: int | None = None


# ─── Response schemas ─────────────────────────────────────────────────────


class VariableInfo(BaseModel):
    name: str
    label: str = ""
    type: str = ""  # "numeric", "string", "date"
    n_values: int = 0
    values: dict | None = None  # {code: label} for categoricals


class DatasetMetadataOut(BaseModel):
    n_cases: int
    n_variables: int
    variables: list[VariableInfo] = []


class FileOut(BaseModel):
    id: UUID
    file_type: str
    original_name: str
    size_bytes: int
    uploaded_at: datetime


class ProjectOut(BaseModel):
    id: UUID
    name: str
    description: str | None = None
    status: str
    owner_type: str = "user"
    created_at: datetime
    updated_at: datetime

    # Study context
    study_objective: str | None = None
    country: str | None = None
    industry: str | None = None
    target_audience: str | None = None
    brands: list[str] | None = None
    methodology: str | None = None
    study_date: date | None = None
    is_tracking: bool = False
    report_language: str = "en"
    low_base_threshold: int = 20

    # Nested data (populated on detail view)
    files: list[FileOut] = []
    metadata: DatasetMetadataOut | None = None

    model_config = {"from_attributes": True}


class ProjectListOut(BaseModel):
    id: UUID
    name: str
    description: str | None = None
    status: str
    created_at: datetime
    file_count: int = 0
    n_cases: int | None = None
    n_variables: int | None = None

    model_config = {"from_attributes": True}


class FileUploadOut(BaseModel):
    file_id: UUID
    original_name: str
    size_bytes: int
    file_type: str
    n_cases: int | None = None
    n_variables: int | None = None
