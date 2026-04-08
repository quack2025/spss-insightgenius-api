"""Pydantic schemas for Teams API."""
from uuid import UUID
from datetime import datetime
from pydantic import BaseModel, Field


class TeamCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None

class TeamUpdate(BaseModel):
    name: str | None = None
    description: str | None = None

class MemberAdd(BaseModel):
    email: str
    role: str = "viewer"  # owner, editor, viewer

class MemberOut(BaseModel):
    user_id: UUID
    role: str
    model_config = {"from_attributes": True}

class TeamOut(BaseModel):
    id: UUID
    name: str
    description: str | None = None
    created_at: datetime
    member_count: int = 0
    model_config = {"from_attributes": True}
