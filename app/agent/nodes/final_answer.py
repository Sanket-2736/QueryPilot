"""Final answer node: returns the agent result."""

import logging
from typing import Any

from app.agent.state import AgentState

logger = logging.getLogger(__name__)


def final_answer(state: AgentState) -> dict[str, Any]:
    """Final answer node: log and return the completed state.

    Args:
        state: Current agent state.

    Returns:
        State (unchanged, just increments iterations).
    """
    logger.info(f"Final answer: status={state['status']}, answer={state['answer'][:100] if state['answer'] else 'N/A'}...")

    state["iterations"] = state["iterations"] + 1

    return state
