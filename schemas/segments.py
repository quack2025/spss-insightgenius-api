"""Pydantic schemas for Segments API."""

from typing import Any
from uuid import UUID
from pydantic import BaseModel, Field


class SegmentCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    conditions: list[dict[str, Any]] = []
    # Format: [{"group": [{"variable": "X", "operator": "in", "values": [1,2]}]}]


class SegmentUpdate(BaseModel):
    name: str | None = None
    conditions: list[dict[str, Any]] | None = None


class SegmentOut(BaseModel):
    id: UUID
    name: str
    conditions: list[dict[str, Any]]
    model_config = {"from_attributes": True}


class SegmentPreviewRequest(BaseModel):
    conditions: list[dict[str, Any]]
