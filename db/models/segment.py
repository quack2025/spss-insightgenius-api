"""Segment model — reusable audience filter definitions."""

import uuid
from typing import Any

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column

from db.database import Base
from db.base import UUIDMixin, TimestampMixin


class Segment(Base, UUIDMixin, TimestampMixin):
    """A named, reusable audience filter (e.g., 'Women 25-34 in Bogota')."""

    __tablename__ = "segments"

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(255))
    conditions: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    # conditions format: [{"group": [{"variable": "X", "operator": "in", "values": [1,2]}]}]
