"""Conversation and Message models for NL chat."""

import enum
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.database import Base
from db.base import UUIDMixin, TimestampMixin


class MessageRole(str, enum.Enum):
    USER = "user"
    ASSISTANT = "assistant"


class Conversation(Base, UUIDMixin, TimestampMixin):
    """A chat conversation within a project."""

    __tablename__ = "conversations"

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(255), default="New conversation")

    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="Message.created_at",
    )


class Message(Base, UUIDMixin):
    """A single message in a conversation (user question or assistant response)."""

    __tablename__ = "messages"

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        index=True,
    )
    role: Mapped[MessageRole] = mapped_column(
        Enum(MessageRole, values_callable=lambda x: [e.value for e in x])
    )
    content: Mapped[str] = mapped_column(Text, default="")

    # Structured data for assistant messages
    analyses_performed: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSON, nullable=True
    )
    charts: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSON, nullable=True
    )
    variables_used: Mapped[list[str] | None] = mapped_column(
        JSON, nullable=True
    )
    python_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    warnings: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )

    conversation: Mapped["Conversation"] = relationship(back_populates="messages")
