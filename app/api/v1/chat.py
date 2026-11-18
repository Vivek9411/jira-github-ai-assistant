"""Chat and AI assistant endpoints with real-time response generation and history."""

import json
import uuid
from typing import Annotated
from collections.abc import AsyncGenerator
from fastapi import APIRouter, Header, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from app.api.deps import CurrentUserDep, SessionDep
from app.models.chat import ChatMessage, ChatSession
from app.schemas.chat import (
    ChatMessageIn,
    ChatMessageOut,
    ChatSessionOut,
    ClientCredentials,
)
from app.services.agent_service import agent_service

router = APIRouter(prefix="/chat", tags=["Chat & Assistant"])


def _resolve_client_credentials(
    payload: ChatMessageIn,
    x_jira_domain: str | None,
    x_jira_email: str | None,
    x_jira_token: str | None,
    x_github_token: str | None,
    x_github_repo: str | None,
) -> ClientCredentials:
    """Resolve credentials prioritizing request body or request headers (Zero-Knowledge BYOK)."""
    creds = payload.credentials or ClientCredentials()
    return ClientCredentials(
        jira_domain=creds.jira_domain or x_jira_domain,
        jira_email=creds.jira_email or x_jira_email,
        jira_token=creds.jira_token or x_jira_token,
        github_token=creds.github_token or x_github_token,
        github_repo=creds.github_repo or x_github_repo,
    )


async def _get_or_create_session(
    session: SessionDep, user_id: uuid.UUID, session_id: uuid.UUID | None, initial_title: str
) -> ChatSession:
    """Retrieve existing user session or create a new one."""
    if session_id:
        query = select(ChatSession).where(
            ChatSession.id == session_id,
            ChatSession.user_id == user_id,
        )
        result = await session.execute(query)
        chat_sess = result.scalar_one_or_none()
        if chat_sess:
            return chat_sess

    # Create new session
    title = initial_title[:40] if initial_title else "New Conversation"
    new_sess = ChatSession(user_id=user_id, title=title)
    session.add(new_sess)
    await session.flush()
    return new_sess


@router.post(
    "/message",
    response_model=ChatMessageOut,
    status_code=status.HTTP_200_OK,
    summary="Send Chat Message (Synchronous)",
    description="Send a message to the AI assistant with optional client-side in-memory credentials.",
)
async def send_message(
    payload: ChatMessageIn,
    current_user: CurrentUserDep,
    session: SessionDep,
    x_jira_domain: Annotated[str | None, Header(alias="X-Jira-Domain")] = None,
    x_jira_email: Annotated[str | None, Header(alias="X-Jira-Email")] = None,
    x_jira_token: Annotated[str | None, Header(alias="X-Jira-Token")] = None,
    x_github_token: Annotated[str | None, Header(alias="X-GitHub-Token")] = None,
    x_github_repo: Annotated[str | None, Header(alias="X-GitHub-Repo")] = None,
) -> ChatMessageOut:
    chat_session = await _get_or_create_session(session, current_user.id, payload.session_id, payload.content)
    client_creds = _resolve_client_credentials(
        payload, x_jira_domain, x_jira_email, x_jira_token, x_github_token, x_github_repo
    )

    # 1. Store user message
    user_msg = ChatMessage(
        session_id=chat_session.id,
        sender="user",
        content=payload.content,
    )
    session.add(user_msg)
    await session.flush()

    # 2. Process with Agent using in-memory client credentials
    agent_output = await agent_service.process_user_message(
        session=session,
        user=current_user,
        user_message=payload.content,
        client_credentials=client_creds,
    )

    # 3. Store assistant message
    assistant_msg = ChatMessage(
        session_id=chat_session.id,
        sender="assistant",
        content=agent_output["response"],
        tool_calls=agent_output.get("tool_calls", []),
    )
    session.add(assistant_msg)
    await session.commit()
    await session.refresh(assistant_msg)

    out = ChatMessageOut.model_validate(assistant_msg)
    out.requires_keys = agent_output.get("requires_keys", False)
    return out


@router.post(
    "/stream",
    summary="Send Chat Message (Streaming SSE)",
    description="Stream real-time assistant responses and tool execution events using Server-Sent Events (SSE).",
)
async def stream_message(
    payload: ChatMessageIn,
    current_user: CurrentUserDep,
    session: SessionDep,
    x_jira_domain: Annotated[str | None, Header(alias="X-Jira-Domain")] = None,
    x_jira_email: Annotated[str | None, Header(alias="X-Jira-Email")] = None,
    x_jira_token: Annotated[str | None, Header(alias="X-Jira-Token")] = None,
    x_github_token: Annotated[str | None, Header(alias="X-GitHub-Token")] = None,
    x_github_repo: Annotated[str | None, Header(alias="X-GitHub-Repo")] = None,
) -> StreamingResponse:
    chat_session = await _get_or_create_session(session, current_user.id, payload.session_id, payload.content)
    client_creds = _resolve_client_credentials(
        payload, x_jira_domain, x_jira_email, x_jira_token, x_github_token, x_github_repo
    )

    # Store user message
    user_msg = ChatMessage(
        session_id=chat_session.id,
        sender="user",
        content=payload.content,
    )
    session.add(user_msg)
    await session.commit()

    async def event_generator() -> AsyncGenerator[str, None]:
        # Send initial status
        yield f"event: status\ndata: {json.dumps({'message': 'Analyzing request intent...'})}\n\n"

        # Execute agent with in-memory client credentials
        output = await agent_service.process_user_message(
            session=session,
            user=current_user,
            user_message=payload.content,
            client_credentials=client_creds,
        )

        # Notify about tool calls if any
        for tool in output.get("tool_calls", []):
            yield f"event: tool_call\ndata: {json.dumps(tool)}\n\n"

        # Stream content
        yield f"event: message\ndata: {json.dumps({'content': output['response']})}\n\n"

        # Persist assistant response
        assistant_msg = ChatMessage(
            session_id=chat_session.id,
            sender="assistant",
            content=output["response"],
            tool_calls=output.get("tool_calls", []),
        )
        session.add(assistant_msg)
        await session.commit()

        yield f"event: done\ndata: {json.dumps({'session_id': str(chat_session.id), 'requires_keys': output.get('requires_keys', False)})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.get(
    "/sessions",
    response_model=list[ChatSessionOut],
    status_code=status.HTTP_200_OK,
    summary="List Chat Sessions",
    description="Retrieve all chat sessions for the authenticated user.",
)
async def list_chat_sessions(
    current_user: CurrentUserDep,
    session: SessionDep,
) -> list[ChatSessionOut]:
    query = (
        select(ChatSession)
        .where(ChatSession.user_id == current_user.id)
        .order_by(ChatSession.created_at.desc())
    )
    result = await session.execute(query)
    sessions = result.scalars().all()
    return [ChatSessionOut.model_validate(s) for s in sessions]
