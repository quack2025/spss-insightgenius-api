"""Pydantic schemas for Explore Mode API."""

from typing import Any
from uuid import UUID
from pydantic import BaseModel, Field


class ExploreRunRequest(BaseModel):
    variable: str
    analysis_type: str = "frequency"  # frequency, crosstab, means, nps, descriptive, correlation
    cross_variable: str | None = None
    weight: str | None = None
    segment_id: UUID | None = None
    filters: list[dict] | None = None
    significance_level: float = 0.95
    net_codes: dict[str, list[int]] | None = None  # {"T2B": [4,5]}


class BookmarkCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    config: dict[str, Any] = {}


class BookmarkOut(BaseModel):
    id: UUID
    name: str
    config: dict[str, Any]
    model_config = {"from_attributes": True}
