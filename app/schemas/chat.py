"""Pydantic schemas for chat sessions and message exchanges."""

import uuid
from datetime import datetime
from typing import Any
from pydantic import BaseModel, ConfigDict, Field


class ClientCredentials(BaseModel):
    """Optional client-side credentials supplied via localStorage (Zero-Knowledge BYOK)."""
    jira_domain: str | None = Field(None, description="Atlassian Jira domain (e.g. acme.atlassian.net)")
    jira_email: str | None = Field(None, description="Atlassian account email")
    jira_token: str | None = Field(None, description="Atlassian REST API token from browser localStorage")
    github_token: str | None = Field(None, description="GitHub Personal Access Token from browser localStorage")
    github_repo: str | None = Field(None, description="Default GitHub repository (e.g. owner/repo)")


class ChatMessageIn(BaseModel):
    """Schema for incoming user chat message."""
    session_id: uuid.UUID | None = Field(None, description="Existing chat session ID; creates new session if omitted")
    content: str = Field(..., min_length=1, max_length=4000, description="Natural language prompt or query")
    credentials: ClientCredentials | None = Field(None, description="In-memory client credentials from localStorage")


class ChatMessageOut(BaseModel):
    """Schema for individual chat messages."""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    sender: str
    content: str
    tool_calls: list[dict[str, Any]] | None = None
    requires_keys: bool = False
    created_at: datetime


class ChatSessionOut(BaseModel):
    """Schema for chat session details including message history."""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    created_at: datetime
    messages: list[ChatMessageOut] = []
