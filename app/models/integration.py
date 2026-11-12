"""User third-party integrations (Jira & GitHub) database models."""

import uuid
from typing import Any
from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base, TimestampMixin


class UserIntegration(Base, TimestampMixin):
    __tablename__ = "user_integrations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(
        String(50), # "jira" | "github"
        nullable=False,
    )
    # Encrypted via TokenVault (AES-256 Fernet)
    encrypted_token: Mapped[str] = mapped_column(
        String(1024),
        nullable=False,
    )
    base_url: Mapped[str | None] = mapped_column(
        String(255), # e.g. "my-team.atlassian.net"
        nullable=True,
    )
    account_email: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
    extra_metadata: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        default=dict,
        nullable=True,
    )

    user: Mapped["User"] = relationship(
        "User",
        back_populates="integrations",
    )

    __table_args__ = (
        UniqueConstraint("user_id", "provider", name="uq_user_provider"),
    )
