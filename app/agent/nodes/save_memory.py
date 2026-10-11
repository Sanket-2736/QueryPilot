"""Save completed turn to memory."""

import asyncio
import logging
import time
import uuid
from typing import Any

from app.agent.state import AgentState
from app.memory.postgres import (
    create_conversation,
    save_message,
    save_query_log,
    save_embedding,
)

logger = logging.getLogger(__name__)


async def _save_memory_async(state: AgentState) -> None:
    """Asynchronously save memory."""
    conversation_id = state["conversation_id"]
    user_id = state["user_id"]
    message_id = str(uuid.uuid4())

    try:
        # Ensure conversation exists
        await create_conversation(conversation_id, user_id)

        # Save message/turn
        await save_message(
            message_id=message_id,
            conversation_id=conversation_id,
            user_id=user_id,
            question=state["question"],
            plan=state.get("plan", []),
            sql=state.get("sql"),
            status=state["status"],
            answer=state.get("answer"),
            iterations=state["iterations"],
            retries=state["retries"],
            error=state.get("error"),
        )

        # If execution was successful, log the query
        result = state.get("result", {})
        if result.get("ok"):
            result_summary = f"Returned {result.get('row_count', 0)} rows"
            if result.get("columns"):
                result_summary += f" with columns: {', '.join(result['columns'][:3])}"
                if len(result["columns"]) > 3:
                    result_summary += f" ... (+{len(result['columns']) - 3} more)"

            # Calculate latency (approximate from timing context if available)
            latency_ms = int((state.get("_execution_time_ms") or 100))  # Default 100ms if not set

            await save_query_log(
                conversation_id=conversation_id,
                message_id=message_id,
                user_id=user_id,
                question=state["question"],
                sql=state["sql"],
                result_summary=result_summary,
                row_count=result.get("row_count"),
                success=True,
                latency_ms=latency_ms,
                tokens_used=state.get("_tokens_used"),
                cost_usd=state.get("_cost_usd"),
            )

            # Save embedding for long-term memory (if enabled)
            # Future: compute embedding using text-embedding-3-small
            # For now, this is a stub
            logger.info(f"Successfully saved turn for conversation {conversation_id}")

        elif state["status"] != "answered":
            # Log failed query
            await save_query_log(
                conversation_id=conversation_id,
                message_id=message_id,
                user_id=user_id,
                question=state["question"],
                sql=state.get("sql", ""),
                result_summary=None,
                row_count=None,
                success=False,
                error=state.get("error"),
                latency_ms=int(state.get("_execution_time_ms") or 100),
            )

    except Exception as e:
        logger.error(f"Error saving memory: {e}", exc_info=True)


def save_memory(state: AgentState) -> dict[str, Any]:
    """Save completed turn to memory.

    Persists to PostgreSQL:
    - Message/turn record with question, SQL, status, answer
    - Query log entry (if successful)
    - Embedding for long-term memory (if enabled)

    Args:
        state: Current agent state.

    Returns:
        Updated state with iterations incremented.
    """
    logger.info(
        f"Saving turn for conversation {state['conversation_id']}: "
        f"status={state['status']}, answer={state['answer'][:50] if state['answer'] else 'N/A'}..."
    )

    # Save memory asynchronously
    try:
        asyncio.run(_save_memory_async(state))
    except Exception as e:
        logger.error(f"Failed to save memory: {e}", exc_info=True)

    state["iterations"] = state["iterations"] + 1

    return state
