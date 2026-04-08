"""Pydantic schemas for Dashboards and Share Links APIs."""
from typing import Any
from uuid import UUID
from datetime import datetime
from pydantic import BaseModel, Field


class DashboardCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    widgets: list[dict[str, Any]] = []

class DashboardUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    widgets: list[dict[str, Any]] | None = None
    filters: dict[str, Any] | None = None

class DashboardOut(BaseModel):
    id: UUID
    name: str
    description: str | None = None
    widgets: list[dict[str, Any]] = []
    is_published: bool = False
    share_token: str | None = None
    created_at: datetime
    model_config = {"from_attributes": True}

class WidgetAdd(BaseModel):
    widget_type: str  # chart, table, text
    position: dict[str, Any] = {}
    config: dict[str, Any] = {}

class ShareLinkCreate(BaseModel):
    password: str | None = None
    expires_in_hours: int | None = None  # None = no expiry

class ShareLinkOut(BaseModel):
    id: UUID
    token: str
    expires_at: datetime | None = None
    view_count: int = 0
    is_active: bool = True
    created_at: datetime
    model_config = {"from_attributes": True}

class UserPreferencesUpdate(BaseModel):
    language: str | None = None
    confidence_level: str | None = None
    default_prompt: str | None = None

class UserProfileOut(BaseModel):
    id: UUID
    email: str
    name: str
    plan: str
    created_at: datetime
    model_config = {"from_attributes": True}
