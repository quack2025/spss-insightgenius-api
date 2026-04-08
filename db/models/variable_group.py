"""Variable Group model — groups related variables (MRS, grids, batteries)."""

import uuid
from typing import Any

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import ARRAY, JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column

from db.database import Base
from db.base import UUIDMixin, TimestampMixin


class VariableGroup(Base, UUIDMixin, TimestampMixin):
    """A named group of related variables (e.g., MRS brand awareness questions)."""

    __tablename__ = "variable_groups"

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    group_type: Mapped[str] = mapped_column(String(50), default="mrs")  # mrs, grid, tom, custom
    variables: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    parent_group_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    hidden_by_group: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
