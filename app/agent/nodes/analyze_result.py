"""Analyze query results and generate final answer."""

import logging
from typing import Any

from langchain_openai import ChatOpenAI

from app.agent.state import AgentState
from app.config import get_config

logger = logging.getLogger(__name__)


def analyze_result(state: AgentState) -> dict[str, Any]:
    """Analyze result and generate natural language answer.

    Args:
        state: Current agent state with execution result.

    Returns:
        Updated state with answer and status set to "answered".
    """
    logger.info("Analyzing result")
    config = get_config()

    try:
        # Initialize LLM
        llm = ChatOpenAI(
            model=config.llm_model,
            temperature=config.llm_temperature,
            max_tokens=config.llm_max_tokens,
            api_key=config.openai_api_key,
        )

        # Load prompt
        with open("app/prompts/analyze_result.txt", "r") as f:
            prompt_template = f.read()

        # Format result for prompt
        result = state.get("result", {})
        if not result.get("ok"):
            result_text = f"Error: {result.get('error', 'Unknown error')}"
        else:
            columns = result.get("columns", [])
            rows = result.get("rows", [])
            if not rows:
                result_text = "No rows returned"
            else:
                # Limit to first 10 rows for display
                rows_display = rows[:10]
                result_text = f"Columns: {columns}\nRows:\n"
                for row in rows_display:
                    result_text += f"  {row}\n"
                if len(rows) > 10:
                    result_text += f"  ... ({len(rows) - 10} more rows)"

        full_prompt = (
            f"{prompt_template}\n\n"
            f"Question: {state['question']}\n\n"
            f"SQL executed:\n{state['sql']}\n\n"
            f"Result:\n{result_text}"
        )

        response = llm.invoke(full_prompt)
        answer = response.content

        logger.info(f"Generated answer: {answer[:100]}...")

        state["answer"] = answer
        state["status"] = "answered"
        state["iterations"] = state["iterations"] + 1

        return state

    except Exception as e:
        logger.error(f"Result analysis failed: {e}", exc_info=True)
        state["error"] = f"Failed to analyze result: {str(e)}"
        state["status"] = "failed"
        state["iterations"] = state["iterations"] + 1
        return state
