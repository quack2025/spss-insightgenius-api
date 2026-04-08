"""Pydantic schemas for Data Preparation API."""

from typing import Any
from uuid import UUID
from pydantic import BaseModel, Field


class DataPrepRuleCreate(BaseModel):
    rule_type: str = Field(..., pattern="^(cleaning|weight|net|recode|computed)$")
    name: str = ""
    description: str | None = None
    config: dict[str, Any] = {}
    is_active: bool = True


class DataPrepRuleUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    config: dict[str, Any] | None = None
    is_active: bool | None = None


class DataPrepRuleOut(BaseModel):
    id: UUID
    rule_type: str
    name: str
    description: str | None = None
    config: dict[str, Any]
    is_active: bool
    order_index: int
    model_config = {"from_attributes": True}


class ReorderRequest(BaseModel):
    rule_ids: list[UUID]


class PreviewRequest(BaseModel):
    rule_type: str
    config: dict[str, Any]
