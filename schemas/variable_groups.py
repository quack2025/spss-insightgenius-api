"""Pydantic schemas for Variable Groups API."""

from uuid import UUID
from pydantic import BaseModel, Field


class VariableGroupCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    display_name: str | None = None
    group_type: str = "mrs"  # mrs, grid, tom, custom
    variables: list[str] = []


class VariableGroupUpdate(BaseModel):
    name: str | None = None
    display_name: str | None = None
    group_type: str | None = None
    variables: list[str] | None = None


class VariableGroupOut(BaseModel):
    id: UUID
    name: str
    display_name: str | None = None
    group_type: str
    variables: list[str]
    model_config = {"from_attributes": True}
