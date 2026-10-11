"""Planner node: breaks questions into steps and decides schema need."""

import json
import logging
from typing import Any

from langchain_openai import ChatOpenAI
from pydantic import BaseModel, ValidationError as PydanticValidationError

from app.agent.state import AgentState
from app.config import get_config

logger = logging.getLogger(__name__)


class PlannerOutput(BaseModel):
    """Structured output from planner."""

    plan: list[str]
    needs_schema: bool
    ambiguity_flag: bool
    clarifying_question: str = ""


def planner(state: AgentState) -> dict[str, Any]:
    """Planner node: breaks question into steps and flags ambiguity.

    Handles follow-ups by referencing successful previous queries.

    Args:
        state: Current agent state.

    Returns:
        Updated state with plan, needs_schema, and status set.
    """
    logger.info(f"Planning question: {state['question']}")
    config = get_config()

    # Initialize LLM
    llm = ChatOpenAI(
        model=config.llm_model,
        temperature=config.llm_temperature,
        max_tokens=config.llm_max_tokens,
        api_key=config.openai_api_key,
    )

    # Load prompt
    with open("app/prompts/planner.txt", "r") as f:
        prompt_template = f.read()

    # Build full prompt with conversation history
    history_text = ""
    if state.get("history"):
        history_text = "Conversation history:\n"
        for h in state["history"][-3:]:  # Last 3 turns
            history_text += f"Q: {h.get('question', '')}\n"
            if h.get('sql'):
                history_text += f"SQL: {h['sql']}\n"
            history_text += f"A: {h.get('answer', '')}\n\n"

    # Include few-shot examples if long-term memory is enabled and available
    few_shot_text = ""
    if state.get("few_shot_examples"):
        few_shot_text = "\nSimilar past queries that worked well:\n"
        for i, example in enumerate(state["few_shot_examples"], 1):
            few_shot_text += f"{i}. Q: {example.get('question', '')}\n"
            few_shot_text += f"   SQL: {example.get('sql', '')}\n"
            few_shot_text += f"   Result: {example.get('result_summary', '')}\n"

    full_prompt = (
        f"{prompt_template}\n\n"
        f"{history_text}"
        f"{few_shot_text}"
        f"\nCurrent question: {state['question']}"
    )

    # Attempt to get structured output with retries
    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = llm.invoke(full_prompt)
            response_text = response.content

            # Try to parse as JSON
            output_dict = json.loads(response_text)
            output = PlannerOutput(**output_dict)

            logger.info(f"Planner output: {output}")

            # Check for ambiguity
            if output.ambiguity_flag:
                state["status"] = "needs_clarification"
                state["answer"] = output.clarifying_question
                state["iterations"] = state["iterations"] + 1
                return state

            # Update state with plan
            state["plan"] = output.plan
            state["needs_schema"] = output.needs_schema
            state["status"] = "running"
            state["iterations"] = state["iterations"] + 1

            return state

        except (json.JSONDecodeError, PydanticValidationError) as e:
            logger.warning(f"Planner JSON parse attempt {attempt + 1} failed: {e}")
            if attempt == max_retries - 1:
                # Final attempt failed
                state["status"] = "failed"
                state["error"] = f"Planner could not produce valid JSON after {max_retries} retries"
                state["iterations"] = state["iterations"] + 1
                return state
            # Retry with error instruction
            full_prompt = (
                f"{full_prompt}\n\n"
                f"ERROR: Invalid JSON in previous attempt. Please return valid JSON only."
            )

    # Should not reach here, but just in case
    state["status"] = "failed"
    state["error"] = "Planner failed unexpectedly"
    state["iterations"] = state["iterations"] + 1
    return state
