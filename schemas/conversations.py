"""Pydantic schemas for Conversations API."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


# ─── Request schemas ──────────────────────────────────────────────────────


class ConversationCreate(BaseModel):
    title: str = "New conversation"


class QueryRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=5000)
    segment_id: UUID | None = None
    filters: list[dict] | None = None
    confidence_level: float | None = None  # 0.90, 0.95, 0.99


class RefineRequest(BaseModel):
    action: str  # "add_significance", "change_banner", "add_weight", etc.
    params: dict = {}


# ─── Response schemas ─────────────────────────────────────────────────────


class AnalysisResult(BaseModel):
    type: str  # "frequency", "crosstab", "nps", etc.
    variable: str | None = None
    cross_variable: str | None = None
    success: bool = True
    result: dict | None = None
    chart: dict | None = None
    error: str | None = None


class QueryResponse(BaseModel):
    message_id: UUID
    answer: str
    analyses: list[AnalysisResult] = []
    variables_used: list[str] = []
    python_code: str | None = None
    warnings: list[str] = []


class MessageOut(BaseModel):
    id: UUID
    role: str
    content: str
    analyses_performed: list[dict] | None = None
    charts: list[dict] | None = None
    variables_used: list[str] | None = None
    python_code: str | None = None
    warnings: list[str] | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ConversationOut(BaseModel):
    id: UUID
    project_id: UUID
    title: str
    created_at: datetime
    updated_at: datetime
    message_count: int = 0

    model_config = {"from_attributes": True}


class ConversationDetailOut(BaseModel):
    id: UUID
    project_id: UUID
    title: str
    created_at: datetime
    messages: list[MessageOut] = []

    model_config = {"from_attributes": True}


class SuggestionOut(BaseModel):
    text: str
    type: str = "analysis"  # "analysis", "explore", "report"
