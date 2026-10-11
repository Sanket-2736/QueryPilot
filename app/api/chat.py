"""Chat endpoint for text-to-SQL queries with SSE streaming."""

import asyncio
import json
import logging
import uuid
from typing import AsyncGenerator, Optional

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field
from starlette.responses import StreamingResponse

from app.config import get_config
from app.middleware import get_request_id, get_user_id
from app.observability import trace_request, trace_span

logger = logging.getLogger(__name__)

router = APIRouter()


class ChatRequest(BaseModel):
    """Request model for chat endpoint."""

    conversation_id: Optional[str] = Field(default=None, description="Conversation ID (generated if not provided)")
    user_id: str = Field(..., description="User ID")
    question: str = Field(..., description="Natural language question")


class ChatEvent(BaseModel):
    """SSE event model."""

    event_type: str = Field(..., description="Event type: node_start, node_end, final_answer, error")
    node_name: Optional[str] = Field(default=None, description="Name of the node (e.g., planner, generate_sql)")
    data: dict = Field(default_factory=dict, description="Event data")
    timestamp: float = Field(..., description="Event timestamp in seconds")


class ChatResponse(BaseModel):
    """Final chat response model."""

    conversation_id: str
    message_id: str
    question: str
    plan: Optional[list[str]] = None
    sql: Optional[str] = None
    result: Optional[dict] = None
    answer: str
    status: str
    iterations: int
    retries: int
    error: Optional[str] = None


async def stream_chat_events(
    conversation_id: str,
    user_id: str,
    question: str,
    request_id: str,
    trace: Optional[object] = None,
) -> AsyncGenerator[str, None]:
    """Stream chat events via SSE.

    Args:
        conversation_id: Conversation ID
        user_id: User ID
        question: User question
        request_id: Request ID for tracing
        trace: Langfuse trace object

    Yields:
        SSE formatted event strings
    """
    config = get_config()
    message_id = str(uuid.uuid4())

    try:
        # TODO: Integrate with LangGraph agent
        # For now, yield placeholder events

        # Simulate node execution
        nodes = ["load_memory", "planner", "retrieve_schema", "generate_sql", "validate_sql", "execute_sql", "analyze_result", "final_answer"]

        for node_name in nodes:
            # Node start event
            start_event = ChatEvent(
                event_type="node_start",
                node_name=node_name,
                data={"status": "running"},
                timestamp=asyncio.get_event_loop().time(),
            )
            yield f"data: {json.dumps(start_event.model_dump())}\n\n"

            # Simulate processing
            await asyncio.sleep(0.1)

            # Node end event
            end_event = ChatEvent(
                event_type="node_end",
                node_name=node_name,
                data={"status": "completed", "iterations": 1},
                timestamp=asyncio.get_event_loop().time(),
            )
            yield f"data: {json.dumps(end_event.model_dump())}\n\n"

        # Final answer event
        final_event = ChatEvent(
            event_type="final_answer",
            data={
                "status": "answered",
                "answer": "Query executed successfully",
                "sql": "SELECT * FROM customers LIMIT 10;",
            },
            timestamp=asyncio.get_event_loop().time(),
        )
        yield f"data: {json.dumps(final_event.model_dump())}\n\n"

    except Exception as e:
        logger.error(f"Error in chat stream: {e}", exc_info=True)
        error_event = ChatEvent(
            event_type="error",
            data={"error": str(e)},
            timestamp=asyncio.get_event_loop().time(),
        )
        yield f"data: {json.dumps(error_event.model_dump())}\n\n"


@router.post("/stream")
async def chat_stream(request: ChatRequest, http_request: Request) -> StreamingResponse:
    """Stream chat response via Server-Sent Events (SSE).

    This endpoint streams node-by-node progress events from the LangGraph agent,
    allowing clients to show real-time feedback as the agent executes.

    Args:
        request: Chat request with question and context.
        http_request: FastAPI HTTP request for context.

    Returns:
        StreamingResponse with SSE events.
    """
    config = get_config()
    conversation_id = request.conversation_id or str(uuid.uuid4())
    request_id = http_request.state.request_id
    user_id = http_request.state.user_id

    logger.info(
        json.dumps({
            "event": "chat_request",
            "request_id": request_id,
            "user_id": user_id,
            "conversation_id": conversation_id,
            "question_length": len(request.question),
        })
    )

    # Create trace for this request
    trace = trace_request(
        name="chat_request",
        request_id=request_id,
        user_id=user_id,
        metadata={
            "conversation_id": conversation_id,
            "question": request.question[:100],
        },
    )

    return StreamingResponse(
        stream_chat_events(
            conversation_id=conversation_id,
            user_id=user_id,
            question=request.question,
            request_id=request_id,
            trace=trace,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "X-Request-ID": request_id,
        },
    )


@router.post("/")
async def chat(request: ChatRequest, http_request: Request) -> ChatResponse:
    """Process a text-to-SQL query and return full response.

    This is a non-streaming endpoint that waits for the full response
    before returning. Use /stream endpoint for real-time updates.

    Args:
        request: Chat request with question and context.
        http_request: FastAPI HTTP request for context.

    Returns:
        ChatResponse with generated SQL and results.
    """
    config = get_config()
    conversation_id = request.conversation_id or str(uuid.uuid4())
    message_id = str(uuid.uuid4())
    request_id = http_request.state.request_id
    user_id = http_request.state.user_id

    logger.info(
        json.dumps({
            "event": "chat_request",
            "request_id": request_id,
            "user_id": user_id,
            "conversation_id": conversation_id,
            "endpoint": "non_streaming",
            "question_length": len(request.question),
        })
    )

    try:
        # Create trace for this request
        trace = trace_request(
            name="chat_request",
            request_id=request_id,
            user_id=user_id,
            metadata={
                "conversation_id": conversation_id,
                "question": request.question[:100],
                "endpoint": "non_streaming",
            },
        )

        # TODO: Integrate with LangGraph agent
        # For now, return a placeholder response

        return ChatResponse(
            conversation_id=conversation_id,
            message_id=message_id,
            question=request.question,
            plan=["Load memory", "Parse question", "Retrieve schema", "Generate SQL", "Validate and execute"],
            sql="SELECT * FROM customers LIMIT 10;",
            result={
                "columns": ["id", "name", "email"],
                "row_count": 10,
                "rows": [],
            },
            answer="Executed successfully",
            status="answered",
            iterations=5,
            retries=0,
        )

    except Exception as e:
        logger.error(
            json.dumps({
                "event": "chat_error",
                "request_id": request_id,
                "user_id": user_id,
                "conversation_id": conversation_id,
                "error": str(e),
            }),
            exc_info=True,
        )
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
