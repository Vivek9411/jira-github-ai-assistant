"""Project mapping database model connecting Jira projects to GitHub repositories."""

import uuid
from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base, TimestampMixin


class ProjectMapping(Base, TimestampMixin):
    __tablename__ = "project_mappings"

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
    jira_project_key: Mapped[str] = mapped_column(
        String(50), # e.g. "PROJ", "ENG"
        index=True,
        nullable=False,
    )
    github_repo: Mapped[str] = mapped_column(
        String(255), # e.g. "owner/repository"
        index=True,
        nullable=False,
    )
    description: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )

    __table_args__ = (
        UniqueConstraint("user_id", "jira_project_key", "github_repo", name="uq_user_jira_github_mapping"),
    )
