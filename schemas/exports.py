"""Pydantic schemas for Exports, Generate Tables, and Reports APIs."""

from typing import Any
from uuid import UUID
from datetime import datetime
from pydantic import BaseModel, Field


# ─── Generate Tables ──────────────────────────────────────────────────────


class GenerateTablesConfig(BaseModel):
    """Configuration for the Generate Tables wizard."""
    banners: list[str] = Field(..., min_length=1, description="Banner (column) variables")
    stubs: list[str] | str = Field("_all_", description="Stub (row) variables or '_all_'")
    significance_level: float = 0.95
    weight: str | None = None
    segment_id: UUID | None = None
    include_means: bool = False
    include_nets: bool = False
    nets: dict[str, list[int]] | None = None  # {"T2B": [4,5], "B2B": [1,2]}
    mrs_groups: list[dict[str, Any]] | None = None
    grid_groups: list[dict[str, Any]] | None = None
    title: str | None = None
    single_sheet: bool = False


class TableTemplateCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    config: dict[str, Any] = {}


class TableTemplateOut(BaseModel):
    id: UUID
    name: str
    config: dict[str, Any]
    created_at: datetime
    model_config = {"from_attributes": True}


# ─── Exports ──────────────────────────────────────────────────────────────


class ExportCreate(BaseModel):
    export_type: str = "excel"  # excel, pdf, pptx
    config: dict[str, Any] = {}


class ExportOut(BaseModel):
    id: UUID
    export_type: str
    status: str
    download_url: str | None = None
    created_at: datetime
    model_config = {"from_attributes": True}


# ─── Reports ──────────────────────────────────────────────────────────────


class ReportCreate(BaseModel):
    title: str = "Report"
    depth: str = "standard"  # compact, standard, detailed


class ReportOut(BaseModel):
    id: UUID
    title: str
    status: str
    progress: int = 0
    created_at: datetime
    model_config = {"from_attributes": True}


class ReportDetailOut(BaseModel):
    id: UUID
    title: str
    status: str
    progress: int
    content: dict[str, Any] | None = None
    file_path: str | None = None
    error_message: str | None = None
    created_at: datetime
    model_config = {"from_attributes": True}
