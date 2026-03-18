"""Response models — the API contract. These shapes must not change without a new version."""

import math
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, field_serializer

T = TypeVar("T")


def _sanitize_float(v):
    """Replace NaN/Infinity with None for JSON serialization."""
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    return v


class ResponseMeta(BaseModel):
    request_id: str
    processing_time_ms: int
    engine_version: str = "1.0.0"
    quantipymrx_available: bool = True


class SuccessResponse(BaseModel, Generic[T]):
    success: Literal[True] = True
    data: T
    meta: ResponseMeta


# --- /v1/metadata ---

class VariableInfo(BaseModel):
    name: str
    label: str | None = None
    type: str  # "numeric", "string", "date"
    measurement: str | None = None  # "scale", "nominal", "ordinal"
    n_valid: int = 0
    n_missing: int = 0
    value_labels: dict[str, str] | None = None
    detected_type: str | None = None  # from auto_detect: "nps", "likert_5", "binary", "mrs", etc.


class MetadataResponse(BaseModel):
    file_name: str = ""
    n_cases: int
    n_variables: int
    variables: list[VariableInfo]
    detected_weights: list[str] = []
    auto_detect: dict[str, Any] | None = None
    file_label: str | None = None


# --- /v1/frequency ---

class FrequencyItem(BaseModel):
    value: Any
    label: str
    count: int | float  # float when weighted
    percentage: float

    @field_serializer("count", "percentage")
    def sanitize(self, v):
        return _sanitize_float(v)


class FrequencyResponse(BaseModel):
    variable: str
    label: str | None = None
    base: int | float = 0
    total_missing: int = 0
    pct_missing: float = 0.0
    frequencies: list[FrequencyItem] = []


# --- /v1/crosstab ---

class CrosstabCell(BaseModel):
    count: int | float
    percentage: float
    column_letter: str = ""
    significance_letters: list[str] = []

    @field_serializer("count", "percentage")
    def sanitize(self, v):
        return _sanitize_float(v)


class CrosstabResponse(BaseModel):
    row_variable: str
    col_variable: str
    total_responses: int = 0
    table: list[dict[str, Any]] = []
    col_labels: dict[str, str] = {}  # {"1.0": "A", "2.0": "B"}
    col_value_labels: dict[str, str] = {}  # {"1.0": "Male", "2.0": "Female"}
    significance_level: float = 0.95
    significant_pairs: list[dict[str, Any]] = []


# --- /v1/process ---

class OperationSpec(BaseModel):
    type: str  # "frequency", "crosstab", "nps", "top_bottom_box", "nets"
    variable: str
    cross_variable: str | None = None
    weight: str | None = None
    params: dict[str, Any] = {}


class OperationResult(BaseModel):
    operation_id: str  # "op_1", "op_2", ...
    type: str
    variable: str
    status: str  # "success" | "error"
    data: dict[str, Any] | None = None
    error: str | None = None


class TicketPlan(BaseModel):
    raw_text: str = ""
    operations: list[OperationSpec] = []
    weight: str | None = None
    filters: list[dict[str, Any]] = []
    notes: list[str] = []


class ProcessResponse(BaseModel):
    metadata: MetadataResponse
    results: list[OperationResult] = []
    ticket_plan: TicketPlan | None = None


# --- NPS ---

class NPSBreakdown(BaseModel):
    count: int
    percentage: float


class NPSResponse(BaseModel):
    variable: str
    label: str | None = None
    nps_score: float
    base: int
    promoters: NPSBreakdown
    passives: NPSBreakdown
    detractors: NPSBreakdown


# --- Top/Bottom Box ---

class BoxScore(BaseModel):
    values: list[Any]
    count: int
    percentage: float


class TopBottomBoxResponse(BaseModel):
    variable: str
    label: str | None = None
    base: int
    top_box: BoxScore
    bottom_box: BoxScore


# --- Nets ---

class NetItem(BaseModel):
    values: list[Any]
    count: int
    percentage: float


class NetsResponse(BaseModel):
    variable: str
    label: str | None = None
    base: int
    nets: dict[str, NetItem]
