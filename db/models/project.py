"""Project, ProjectFile, and DatasetMetadata models."""

import enum
import uuid
from datetime import date, datetime, timezone
from typing import Any, TYPE_CHECKING

from sqlalchemy import Boolean, Date, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.database import Base
from db.base import UUIDMixin, TimestampMixin

if TYPE_CHECKING:
    from db.models.user import User


# ─── Enums ────────────────────────────────────────────────────────────────


class OwnerType(str, enum.Enum):
    USER = "user"
    TEAM = "team"


class ProjectStatus(str, enum.Enum):
    PROCESSING = "processing"
    READY = "ready"
    ERROR = "error"


class FileType(str, enum.Enum):
    SPSS_DATA = "spss_data"
    CSV_DATA = "csv_data"
    EXCEL_DATA = "excel_data"
    QUESTIONNAIRE_PDF = "questionnaire_pdf"


# ─── Project ──────────────────────────────────────────────────────────────


class Project(Base, UUIDMixin, TimestampMixin):
    """A data analysis project — the central entity for platform users."""

    __tablename__ = "projects"

    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    owner_type: Mapped[OwnerType] = mapped_column(
        Enum(OwnerType, values_callable=lambda x: [e.value for e in x]),
        default=OwnerType.USER,
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    status: Mapped[ProjectStatus] = mapped_column(
        Enum(ProjectStatus, values_callable=lambda x: [e.value for e in x]),
        default=ProjectStatus.PROCESSING,
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Study context (used by NL Chat for better interpretation)
    study_objective: Mapped[str | None] = mapped_column(Text, nullable=True)
    country: Mapped[str | None] = mapped_column(String(100), nullable=True)
    industry: Mapped[str | None] = mapped_column(String(100), nullable=True)
    target_audience: Mapped[str | None] = mapped_column(Text, nullable=True)
    brands: Mapped[list[str] | None] = mapped_column(ARRAY(String), nullable=True)
    methodology: Mapped[str | None] = mapped_column(String(100), nullable=True)
    study_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_tracking: Mapped[bool] = mapped_column(Boolean, default=False)
    report_language: Mapped[str] = mapped_column(String(10), default="en")
    low_base_threshold: Mapped[int] = mapped_column(Integer, default=20)

    # Relationships
    files: Mapped[list["ProjectFile"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    dataset_metadata: Mapped["DatasetMetadata | None"] = relationship(
        back_populates="project", uselist=False, cascade="all, delete-orphan"
    )


# ─── ProjectFile ──────────────────────────────────────────────────────────


class ProjectFile(Base, UUIDMixin):
    """An uploaded file belonging to a project."""

    __tablename__ = "project_files"

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    file_type: Mapped[FileType] = mapped_column(
        Enum(FileType, values_callable=lambda x: [e.value for e in x])
    )
    storage_path: Mapped[str] = mapped_column(String(512))
    original_name: Mapped[str] = mapped_column(String(255))
    size_bytes: Mapped[int] = mapped_column(Integer)
    uploaded_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(timezone.utc)
    )

    project: Mapped["Project"] = relationship(back_populates="files")


# ─── DatasetMetadata ──────────────────────────────────────────────────────


class DatasetMetadata(Base, UUIDMixin):
    """Extracted metadata from SPSS/CSV/Excel files — stored once per project."""

    __tablename__ = "dataset_metadata"

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), unique=True
    )
    n_cases: Mapped[int] = mapped_column(Integer)
    n_variables: Mapped[int] = mapped_column(Integer)
    variables: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    basic_frequencies: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    basic_stats: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    variable_profiles: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    user_metadata_overrides: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    processed_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(timezone.utc)
    )

    project: Mapped["Project"] = relationship(back_populates="dataset_metadata")

    @property
    def enriched_variables(self) -> list[dict[str, Any]]:
        """Variables with user overrides applied (labels, value_labels)."""
        overrides = self.user_metadata_overrides or {}
        raw = self.variables or []
        if not overrides:
            return raw
        enriched = []
        for v in raw:
            v_copy = dict(v)
            override = overrides.get(v_copy.get("name", ""), {})
            if "label" in override:
                v_copy["label"] = override["label"]
            if "value_labels" in override and v_copy.get("values"):
                merged = dict(v_copy["values"])
                merged.update(override["value_labels"])
                v_copy["values"] = merged
            enriched.append(v_copy)
        return enriched
