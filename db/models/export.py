"""Export, TableTemplate, and Report models."""

import enum
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column

from db.database import Base
from db.base import UUIDMixin, TimestampMixin


class ExportType(str, enum.Enum):
    EXCEL = "excel"
    PDF = "pdf"
    PPTX = "pptx"


class ExportStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class ReportStatus(str, enum.Enum):
    GENERATING = "generating"
    READY = "ready"
    FAILED = "failed"


class Export(Base, UUIDMixin, TimestampMixin):
    """A generated export file (Excel/PDF/PPTX)."""

    __tablename__ = "exports"

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    export_type: Mapped[ExportType] = mapped_column(
        Enum(ExportType, values_callable=lambda x: [e.value for e in x])
    )
    status: Mapped[ExportStatus] = mapped_column(
        Enum(ExportStatus, values_callable=lambda x: [e.value for e in x]),
        default=ExportStatus.PENDING,
    )
    file_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    download_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class TableTemplate(Base, UUIDMixin, TimestampMixin):
    """A saved Generate Tables configuration."""

    __tablename__ = "table_templates"

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(255))
    config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class Report(Base, UUIDMixin, TimestampMixin):
    """An AI-generated multi-analysis report."""

    __tablename__ = "reports"

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(255), default="Report")
    status: Mapped[ReportStatus] = mapped_column(
        Enum(ReportStatus, values_callable=lambda x: [e.value for e in x]),
        default=ReportStatus.GENERATING,
    )
    progress: Mapped[int] = mapped_column(Integer, default=0)  # 0-100
    content: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    file_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
