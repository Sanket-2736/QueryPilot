"""Chat endpoint for text-to-SQL queries."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()


class ChatRequest(BaseModel):
    """Request model for chat endpoint."""

    conversation_id: str
    user_id: str
    question: str


class ChatResponse(BaseModel):
    """Response model for chat endpoint."""

    conversation_id: str
    message_id: str
    sql: str | None
    result: dict | None
    answer: str
    status: str


@router.post("/")
async def chat(request: ChatRequest) -> ChatResponse:
    """Process a text-to-SQL query.

    Args:
        request: Chat request with question and context.

    Returns:
        ChatResponse with generated SQL and results.
    """
    # TODO: Implement chat endpoint
    raise HTTPException(status_code=501, detail="Not yet implemented")
