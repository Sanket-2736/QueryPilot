"""Conversation management endpoints."""

import json
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, status

from app.middleware import get_request_id

logger = logging.getLogger(__name__)

router = APIRouter()


class Message:
    """Message model."""

    def __init__(
        self,
        id: str,
        conversation_id: str,
        turn_number: int,
        question: str,
        answer: str,
        sql: Optional[str],
        status: str,
        iterations: int,
        retries: int,
    ):
        self.id = id
        self.conversation_id = conversation_id
        self.turn_number = turn_number
        self.question = question
        self.answer = answer
        self.sql = sql
        self.status = status
        self.iterations = iterations
        self.retries = retries

    def to_dict(self):
        return {
            "id": self.id,
            "conversation_id": self.conversation_id,
            "turn_number": self.turn_number,
            "question": self.question,
            "answer": self.answer,
            "sql": self.sql,
            "status": self.status,
            "iterations": self.iterations,
            "retries": self.retries,
        }


@router.get("/{conversation_id}")
async def get_conversation(conversation_id: str, http_request: Request) -> dict:
    """Retrieve conversation history and metadata.

    Args:
        conversation_id: ID of the conversation.
        http_request: FastAPI HTTP request for context.

    Returns:
        Conversation history and metadata.

    Raises:
        HTTPException: If conversation not found.
    """
    request_id = http_request.state.request_id

    logger.info(
        json.dumps({
            "event": "get_conversation",
            "request_id": request_id,
            "conversation_id": conversation_id,
        })
    )

    try:
        # TODO: Retrieve from PostgreSQL using app/memory/postgres.py
        # For now, return placeholder

        return {
            "id": conversation_id,
            "user_id": "user_123",
            "title": "Sample Conversation",
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": "2024-01-02T00:00:00Z",
            "message_count": 3,
        }

    except Exception as e:
        logger.error(
            json.dumps({
                "event": "get_conversation_error",
                "request_id": request_id,
                "conversation_id": conversation_id,
                "error": str(e),
            }),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve conversation",
        )


@router.get("/{conversation_id}/messages")
async def get_messages(
    conversation_id: str,
    limit: int = 50,
    offset: int = 0,
    http_request: Request = None,
) -> dict:
    """Retrieve messages from a conversation.

    Args:
        conversation_id: ID of the conversation.
        limit: Maximum number of messages to return (default: 50).
        offset: Offset for pagination (default: 0).
        http_request: FastAPI HTTP request for context.

    Returns:
        Paginated list of messages in the conversation.

    Raises:
        HTTPException: If conversation not found or retrieval fails.
    """
    request_id = http_request.state.request_id

    if limit < 1 or limit > 100:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Limit must be between 1 and 100",
        )

    logger.info(
        json.dumps({
            "event": "get_messages",
            "request_id": request_id,
            "conversation_id": conversation_id,
            "limit": limit,
            "offset": offset,
        })
    )

    try:
        # TODO: Retrieve from PostgreSQL using app/memory/postgres.py
        # For now, return placeholder

        return {
            "conversation_id": conversation_id,
            "messages": [],
            "total": 0,
            "limit": limit,
            "offset": offset,
        }

    except Exception as e:
        logger.error(
            json.dumps({
                "event": "get_messages_error",
                "request_id": request_id,
                "conversation_id": conversation_id,
                "error": str(e),
            }),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve messages",
        )
