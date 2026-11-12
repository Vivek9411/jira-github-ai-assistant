"""Vector store database model for Jira tickets and linked code diffs."""

import uuid
from typing import Any
from pgvector.sqlalchemy import Vector
from sqlalchemy import String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base, TimestampMixin


class JiraTicketVector(Base, TimestampMixin):
    __tablename__ = "jira_ticket_vectors"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    issue_key: Mapped[str] = mapped_column(
        String(50),
        unique=True,
        index=True,
        nullable=False,
    )
    project_key: Mapped[str] = mapped_column(
        String(50),
        index=True,
        nullable=False,
    )
    summary: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
    )
    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )
    assignee: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
    linked_pr_numbers: Mapped[list[int] | None] = mapped_column(
        JSONB,
        default=list,
        nullable=True,
    )
    code_diff_summary: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    # Default vector dimension 768 (suitable for Gemini text-embedding / nomic)
    embedding: Mapped[list[float]] = mapped_column(
        Vector(768),
        nullable=True,
    )
    extra_metadata: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        default=dict,
        nullable=True,
    )
