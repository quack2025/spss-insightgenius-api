"""Request models for form data parsing."""

from pydantic import BaseModel, Field
from typing import Any


class FrequencyRequest(BaseModel):
    variable: str
    weight: str | None = None


class CrosstabSpec(BaseModel):
    row: str
    col: str
    weight: str | None = None
    significance_level: float = Field(default=0.95, ge=0.5, le=0.999)
    nets: dict[str, list[Any]] | None = None


class ConvertRequest(BaseModel):
    target_format: str = Field(..., pattern="^(xlsx|csv|dta|parquet)$")
    apply_labels: bool = True
    include_metadata_sheet: bool = True
