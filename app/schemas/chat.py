"""Pydantic schemas for chat sessions and message exchanges."""

import uuid
from datetime import datetime
from typing import Any
from pydantic import BaseModel, ConfigDict, Field


class ChatMessageIn(BaseModel):
    """Schema for incoming user chat message."""
    session_id: uuid.UUID | None = Field(None, description="Existing chat session ID; creates new session if omitted")
    content: str = Field(..., min_length=1, max_length=4000, description="Natural language prompt or query")


class ChatMessageOut(BaseModel):
    """Schema for individual chat messages."""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    sender: str
    content: str
    tool_calls: list[dict[str, Any]] | None = None
    created_at: datetime


class ChatSessionOut(BaseModel):
    """Schema for chat session details including message history."""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    created_at: datetime
    messages: list[ChatMessageOut] = []
