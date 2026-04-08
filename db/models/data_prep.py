"""Data Preparation Rule model.

Rules are applied in order before every analysis.
Types: cleaning, weight, net, recode, computed.
"""

import enum
import uuid
from typing import Any

from sqlalchemy import Boolean, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.database import Base
from db.base import UUIDMixin, TimestampMixin


class RuleType(str, enum.Enum):
    CLEANING = "cleaning"
    WEIGHT = "weight"
    NET = "net"
    RECODE = "recode"
    COMPUTED = "computed"


class DataPrepRule(Base, UUIDMixin, TimestampMixin):
    """A data preparation rule applied to a project's dataset."""

    __tablename__ = "data_prep_rules"

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    rule_type: Mapped[RuleType] = mapped_column(
        Enum(RuleType, values_callable=lambda x: [e.value for e in x])
    )
    name: Mapped[str] = mapped_column(String(255), default="")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    order_index: Mapped[int] = mapped_column(Integer, default=0)
