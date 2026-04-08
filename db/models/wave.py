"""ProjectWave model — tracking study waves."""

import uuid

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from db.database import Base
from db.base import UUIDMixin, TimestampMixin


class ProjectWave(Base, UUIDMixin, TimestampMixin):
    """A wave in a tracking study (e.g., Wave 1 Q1 2026)."""

    __tablename__ = "project_waves"

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    wave_name: Mapped[str] = mapped_column(String(255))
    wave_order: Mapped[int] = mapped_column(Integer, default=0)
    file_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project_files.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
