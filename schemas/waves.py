"""Pydantic schemas for Waves API."""

from uuid import UUID
from pydantic import BaseModel, Field


class WaveCreate(BaseModel):
    wave_name: str = Field(..., min_length=1, max_length=255)
    wave_order: int = 0
    file_id: UUID | None = None


class WaveUpdate(BaseModel):
    wave_name: str | None = None
    wave_order: int | None = None


class WaveOut(BaseModel):
    id: UUID
    wave_name: str
    wave_order: int
    file_id: UUID | None = None
    model_config = {"from_attributes": True}


class WaveCompareRequest(BaseModel):
    variable: str
    metric: str = "frequency"  # frequency, mean, nps
    wave_ids: list[UUID] | None = None  # None = all waves
