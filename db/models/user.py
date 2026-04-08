"""User and UserPreferences models.

Users are created/synced automatically on first Supabase JWT login.
No local password — authentication is handled by Supabase Auth.
"""

import enum
import uuid

from sqlalchemy import Enum, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.database import Base
from db.base import UUIDMixin, TimestampMixin


class UserPlan(str, enum.Enum):
    FREE = "free"
    PRO = "pro"
    BUSINESS = "business"
    ENTERPRISE = "enterprise"


class ConfidenceLevel(str, enum.Enum):
    NINETY = "90"
    NINETY_FIVE = "95"
    NINETY_NINE = "99"


class User(Base, UUIDMixin, TimestampMixin):
    """Platform user — synced from Supabase Auth on first login."""

    __tablename__ = "users"

    # Supabase Auth user ID (from JWT sub claim) — used for lookups
    supabase_uid: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255), default="")
    plan: Mapped[UserPlan] = mapped_column(
        Enum(UserPlan, values_callable=lambda x: [e.value for e in x]),
        default=UserPlan.FREE,
    )
    is_active: Mapped[bool] = mapped_column(default=True)

    # Relationships (added as models are created in subsequent phases)
    preferences: Mapped["UserPreferences"] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )


class UserPreferences(Base, UUIDMixin):
    """User preferences for analysis and UI behavior."""

    __tablename__ = "user_preferences"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), unique=True
    )
    language: Mapped[str] = mapped_column(String(10), default="en")
    confidence_level: Mapped[ConfidenceLevel] = mapped_column(
        Enum(ConfidenceLevel, values_callable=lambda x: [e.value for e in x]),
        default=ConfidenceLevel.NINETY_FIVE,
    )
    default_prompt: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)

    user: Mapped["User"] = relationship(back_populates="preferences")
