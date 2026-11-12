"""Chat and AI assistant endpoints with real-time response generation and history."""

import json
import uuid
from collections.abc import AsyncGenerator
from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from app.api.deps import CurrentUserDep, SessionDep
from app.models.chat import ChatMessage, ChatSession
from app.schemas.chat import ChatMessageIn, ChatMessageOut, ChatSessionOut
from app.services.agent_service import agent_service

router = APIRouter(prefix="/chat", tags=["Chat & Assistant"])


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
    description="Send a message to the AI assistant and receive a synthesized response with tool audit.",
)
async def send_message(
    payload: ChatMessageIn,
    current_user: CurrentUserDep,
    session: SessionDep,
) -> ChatMessageOut:
    chat_session = await _get_or_create_session(session, current_user.id, payload.session_id, payload.content)

    # 1. Store user message
    user_msg = ChatMessage(
        session_id=chat_session.id,
        sender="user",
        content=payload.content,
    )
    session.add(user_msg)
    await session.flush()

    # 2. Process with Agent
    agent_output = await agent_service.process_user_message(session, current_user, payload.content)

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

    return ChatMessageOut.model_validate(assistant_msg)


@router.post(
    "/stream",
    summary="Send Chat Message (Streaming SSE)",
    description="Stream real-time assistant responses and tool execution events using Server-Sent Events (SSE).",
)
async def stream_message(
    payload: ChatMessageIn,
    current_user: CurrentUserDep,
    session: SessionDep,
) -> StreamingResponse:
    chat_session = await _get_or_create_session(session, current_user.id, payload.session_id, payload.content)

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

        # Execute agent
        output = await agent_service.process_user_message(session, current_user, payload.content)

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

        yield f"event: done\ndata: {json.dumps({'session_id': str(chat_session.id)})}\n\n"

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
