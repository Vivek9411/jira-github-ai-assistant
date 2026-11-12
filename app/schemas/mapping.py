"""Pydantic schemas for Jira Project to GitHub Repository mappings."""

import uuid
from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field


class ProjectMappingCreate(BaseModel):
    """Schema for linking a Jira project to a GitHub repository."""
    jira_project_key: str = Field(..., min_length=2, max_length=20, description="Jira Project Key e.g. ENG, PROJ")
    github_repo: str = Field(..., min_length=3, max_length=150, description="GitHub repository in owner/repo format")
    description: str | None = Field(None, max_length=500, description="Optional description of this mapping")


class ProjectMappingOut(BaseModel):
    """Schema for returning project mapping details."""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    jira_project_key: str
    github_repo: str
    description: str | None
    created_at: datetime
