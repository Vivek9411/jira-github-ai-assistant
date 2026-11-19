"""Pydantic schemas for third-party integrations (Jira & GitHub)."""

import uuid
from datetime import datetime
from typing import Any
from pydantic import BaseModel, ConfigDict, Field, field_validator
from app.services.jira_client import validate_jira_domain


class JiraConnectIn(BaseModel):
    """Schema for connecting Atlassian Jira credentials."""
    domain: str = Field(..., description="Atlassian domain e.g. company.atlassian.net")
    email: str = Field(..., description="Email associated with Atlassian account")
    api_token: str = Field(..., min_length=10, description="Atlassian REST API token")

    @field_validator("domain")
    @classmethod
    def validate_domain(cls, v: str) -> str:
        return validate_jira_domain(v)


class GitHubConnectIn(BaseModel):
    """Schema for connecting GitHub credentials."""
    personal_access_token: str = Field(..., min_length=10, description="GitHub Fine-Grained or Classic Read PAT")


class IntegrationOut(BaseModel):
    """Schema for returning integration status without leaking tokens."""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    provider: str
    base_url: str | None = None
    account_email: str | None = None
    is_active: bool = True
    created_at: datetime
    updated_at: datetime


class IntegrationStatusResponse(BaseModel):
    """Aggregated status of third-party integrations for the current user."""
    jira_connected: bool
    jira_domain: str | None = None
    github_connected: bool
