"""Conversation management endpoints."""

from fastapi import APIRouter, HTTPException

router = APIRouter()


@router.get("/{conversation_id}")
async def get_conversation(conversation_id: str) -> dict:
    """Retrieve conversation history.

    Args:
        conversation_id: ID of the conversation.

    Returns:
        Conversation history and metadata.
    """
    # TODO: Implement conversation retrieval
    raise HTTPException(status_code=501, detail="Not yet implemented")


@router.get("/{conversation_id}/messages")
async def get_messages(conversation_id: str, limit: int = 50) -> list[dict]:
    """Retrieve messages from a conversation.

    Args:
        conversation_id: ID of the conversation.
        limit: Maximum number of messages to return.

    Returns:
        List of messages in the conversation.
    """
    # TODO: Implement message retrieval
    raise HTTPException(status_code=501, detail="Not yet implemented")
