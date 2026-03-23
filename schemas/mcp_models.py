"""Pydantic input models for SPSS InsightGenius MCP tools.

These models generate the inputSchema that LLMs read to understand
how to call each tool. Descriptions, constraints, and examples are critical.
"""

from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ResponseFormat(str, Enum):
    """Output format for tool responses."""
    JSON = "json"
    MARKDOWN = "markdown"


class FileReference(BaseModel):
    """Base model for tools that reference a data file."""
    model_config = ConfigDict(str_strip_whitespace=True, validate_assignment=True)

    file_id: Optional[str] = Field(
        default=None,
        description="File session ID from spss_upload_file. Preferred — avoids re-uploading.",
    )
    file_base64: Optional[str] = Field(
        default=None,
        description="Base64-encoded file contents. Only use if you don't have a file_id.",
    )
    filename: str = Field(
        default="upload.sav",
        description=(
            "Original filename with extension (e.g., 'survey.sav', 'data.csv', 'export.xlsx'). "
            "Extension determines parser: .sav (SPSS), .csv/.tsv (delimited), .xlsx/.xls (Excel)."
        ),
    )


# ── Upload ──


class UploadFileInput(BaseModel):
    """Upload a data file (.sav, .csv, .xlsx) to create a reusable session."""
    model_config = ConfigDict(str_strip_whitespace=True)

    file_base64: str = Field(
        ...,
        description="Base64-encoded file contents (.sav, .csv, .tsv, .xlsx, .xls)",
    )
    filename: str = Field(
        default="upload.sav",
        description=(
            "Original filename with extension. Extension determines parser. "
            "Examples: 'customer_sat_2026.sav', 'qualtrics_export.csv', 'survey_data.xlsx'"
        ),
    )


# ── Exploration ──


class GetMetadataInput(FileReference):
    """Get full dataset metadata including AI-detected smart fields (banners, groups, nets)."""
    response_format: ResponseFormat = Field(
        default=ResponseFormat.JSON,
        description="'json' for structured data, 'markdown' for human-readable summary",
    )


class DescribeVariableInput(FileReference):
    """Get detailed profile of a single variable: labels, distribution, missing, type."""
    variable: str = Field(
        ..., description="Variable name (e.g., 'Q1_satisfaction', 'gender')", min_length=1
    )
    response_format: ResponseFormat = Field(default=ResponseFormat.JSON)


# ── Analysis ──


def _normalize_sig_level(v: float) -> float:
    """Normalize significance level: accept 90/95/99 or 0.90/0.95/0.99."""
    if v > 1:
        v = v / 100
    if v not in (0.90, 0.95, 0.99):
        raise ValueError("significance_level must be 0.90, 0.95, or 0.99 (or 90, 95, 99)")
    return v


class AnalyzeFrequenciesInput(FileReference):
    """Run frequency analysis on one or more variables (batch up to 50)."""
    variables: list[str] = Field(
        ...,
        description=(
            "Variable names to analyze (e.g., ['Q1_satisfaction', 'Q2_recommend']). "
            "Batch: pass up to 50 variables in one call."
        ),
        min_length=1,
        max_length=50,
    )
    weight: Optional[str] = Field(
        default=None, description="Weight variable name (e.g., 'weight_var')"
    )
    response_format: ResponseFormat = Field(default=ResponseFormat.JSON)


class AnalyzeCrosstabInput(FileReference):
    """Cross-tabulation with column proportion significance testing (z-test)."""
    row: str = Field(
        ..., description="Row variable (stub) — the question (e.g., 'Q1_satisfaction')"
    )
    col: str | list[str] = Field(
        ...,
        description=(
            "Banner variable(s). String for one banner, list for multiple. "
            "Example: 'gender' or ['gender', 'region']"
        ),
    )
    weight: Optional[str] = Field(default=None, description="Weight variable name")
    significance_level: float = Field(
        default=0.95,
        description="Confidence level: 0.90, 0.95, or 0.99 (also accepts 90, 95, 99)",
    )
    nets: Optional[dict[str, dict[str, list[int]]]] = Field(
        default=None,
        description="Net definitions. Example: {'Q1': {'Top 2 Box': [4, 5], 'Bottom 2 Box': [1, 2]}}",
    )
    include_means: bool = Field(
        default=False, description="Include mean row with T-test significance"
    )
    response_format: ResponseFormat = Field(default=ResponseFormat.JSON)

    _normalize_sig = field_validator("significance_level")(_normalize_sig_level)


class AnalyzeCorrelationInput(FileReference):
    """Correlation matrix between numeric variables."""
    variables: list[str] = Field(
        ...,
        description="Numeric variables (e.g., ['sat_speed', 'sat_price'])",
        min_length=2,
        max_length=20,
    )
    method: str = Field(
        default="pearson", description="'pearson', 'spearman', or 'kendall'"
    )
    weight: Optional[str] = Field(default=None)
    response_format: ResponseFormat = Field(default=ResponseFormat.JSON)

    @field_validator("method")
    @classmethod
    def validate_method(cls, v: str) -> str:
        if v not in ("pearson", "spearman", "kendall"):
            raise ValueError("method must be 'pearson', 'spearman', or 'kendall'")
        return v


class AnalyzeAnovaInput(FileReference):
    """One-way ANOVA with optional Tukey HSD post-hoc."""
    dependent: str = Field(
        ..., description="Dependent numeric variable (e.g., 'sat_overall')"
    )
    factor: str = Field(
        ..., description="Grouping categorical variable (e.g., 'region')"
    )
    post_hoc: bool = Field(
        default=True, description="Include Tukey HSD pairwise comparisons"
    )
    weight: Optional[str] = Field(default=None)
    response_format: ResponseFormat = Field(default=ResponseFormat.JSON)


class AnalyzeGapInput(FileReference):
    """Importance-Performance gap analysis with quadrant classification."""
    importance_vars: list[str] = Field(
        ..., description="Importance variables (e.g., ['imp_speed', 'imp_price'])"
    )
    performance_vars: list[str] = Field(
        ..., description="Performance variables, same order as importance_vars"
    )
    weight: Optional[str] = Field(default=None)
    response_format: ResponseFormat = Field(default=ResponseFormat.JSON)


class SummarizeSatisfactionInput(FileReference):
    """Compact T2B/B2B/Mean summary for multiple scale variables."""
    variables: list[str] = Field(
        ..., description="Scale variables (e.g., ['sat_speed', 'sat_price'])"
    )
    weight: Optional[str] = Field(default=None)
    top_box: list[int] = Field(
        default=[4, 5], description="Top Box values (e.g., [4, 5] for 5-point scale)"
    )
    bottom_box: list[int] = Field(
        default=[1, 2], description="Bottom Box values"
    )
    response_format: ResponseFormat = Field(default=ResponseFormat.JSON)


class AutoAnalyzeInput(FileReference):
    """Zero-config: auto-detect banners, groups, nets and produce complete analysis."""
    significance_level: float = Field(default=0.95)
    include_means: bool = Field(
        default=True, description="Include means with T-test"
    )
    response_format: ResponseFormat = Field(default=ResponseFormat.JSON)

    _normalize_sig = field_validator("significance_level")(_normalize_sig_level)


class CreateTabulationInput(FileReference):
    """Full professional Excel tabulation with significance, nets, means, MRS, grids."""
    banners: list[str] = Field(
        ...,
        description=(
            "Banner variables for columns (e.g., ['gender', 'region']). "
            "Use spss_get_metadata to find suggested_banners."
        ),
    )
    stubs: list[str] = Field(
        default=["_all_"],
        description="Row variables. '_all_' for all, or specific (e.g., ['Q1', 'Q2'])",
    )
    significance_level: float = Field(default=0.95)
    weight: Optional[str] = Field(default=None)
    include_means: bool = Field(default=False)
    include_total_column: bool = Field(default=True)
    output_mode: str = Field(
        default="multi_sheet", description="'multi_sheet' or 'single_sheet'"
    )
    nets: Optional[dict[str, dict[str, list[int]]]] = Field(default=None)
    mrs_groups: Optional[dict[str, list[str]]] = Field(
        default=None,
        description="MRS groups. Example: {'Brand_Awareness': ['AWARE_A', 'AWARE_B']}",
    )
    grid_groups: Optional[dict[str, dict]] = Field(default=None)
    custom_groups: Optional[list[dict]] = Field(default=None)
    title: str = Field(default="", description="Report title")
    response_format: ResponseFormat = Field(default=ResponseFormat.JSON)

    _normalize_sig = field_validator("significance_level")(_normalize_sig_level)


class ExportDataInput(FileReference):
    """Convert data file to another format."""
    format: str = Field(
        ..., description="Target format: 'xlsx', 'csv', 'parquet', or 'dta'"
    )

    @field_validator("format")
    @classmethod
    def validate_format(cls, v: str) -> str:
        if v not in ("xlsx", "csv", "parquet", "dta"):
            raise ValueError("format must be 'xlsx', 'csv', 'parquet', or 'dta'")
        return v
