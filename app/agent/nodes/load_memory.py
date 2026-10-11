"""Load previous conversation turns from memory."""

import asyncio
import logging
from typing import Any

from app.agent.state import AgentState
from app.config import get_config
from app.memory.postgres import load_conversation_history, load_successful_queries

logger = logging.getLogger(__name__)


async def _load_memory_async(state: AgentState) -> None:
    """Asynchronously load memory."""
    config = get_config()
    conversation_id = state["conversation_id"]

    try:
        # Load short-term memory: last N turns
        history = await load_conversation_history(
            conversation_id,
            limit=config.memory_history_limit,
        )
        state["history"] = history

        # Load successful queries for few-shot examples (if enabled)
        if config.memory_long_term_enabled:
            successful_queries = await load_successful_queries(
                conversation_id,
                limit=3,
            )
            # Store as few-shot examples in state for later use in generate_sql
            state["few_shot_examples"] = successful_queries

        logger.info(f"Loaded {len(history)} history turns and {len(state.get('few_shot_examples', []))} few-shot examples")

    except Exception as e:
        logger.error(f"Error loading memory: {e}", exc_info=True)
        state["history"] = []


def load_memory(state: AgentState) -> dict[str, Any]:
    """Load previous conversation turns.

    Queries PostgreSQL for:
    - Last N turns of this conversation (short-term memory)
    - Successful queries for few-shot examples (long-term memory, if enabled)

    Args:
        state: Current agent state.

    Returns:
        Updated state with history and few-shot examples loaded.
    """
    logger.info(f"Loading memory for conversation {state['conversation_id']}")

    # Load memory asynchronously
    try:
        asyncio.run(_load_memory_async(state))
    except Exception as e:
        logger.error(f"Failed to load memory: {e}", exc_info=True)
        state["history"] = []

    # Increment iterations
    state["iterations"] = state["iterations"] + 1

    return state
