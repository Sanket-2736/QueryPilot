"""Fix SQL queries that failed."""

import logging
import re
from typing import Any

from langchain_openai import ChatOpenAI

from app.agent.state import AgentState
from app.config import get_config

logger = logging.getLogger(__name__)


def fix_sql(state: AgentState) -> dict[str, Any]:
    """Fix failed SQL.

    Args:
        state: Current agent state with failed SQL and error.

    Returns:
        Updated state with corrected SQL and incremented retries.
    """
    logger.info(f"Fixing SQL (attempt {state['retries'] + 1})")
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
        with open("app/prompts/fix_sql.txt", "r") as f:
            prompt_template = f.read()

        # Build full prompt
        full_prompt = (
            f"{prompt_template}\n\n"
            f"Question: {state['question']}\n\n"
            f"Plan:\n" + "\n".join([f"  - {step}" for step in state["plan"]]) + f"\n\n"
            f"Failed SQL:\n{state['sql']}\n\n"
            f"Error:\n{state.get('error', state['result'].get('error', 'Unknown error'))}\n\n"
            f"Schema:\n{state['schema_context']}"
        )

        response = llm.invoke(full_prompt)
        response_text = response.content

        # Extract SQL from response
        sql_match = re.search(r"(?:```sql\n)?(.*?)(?:\n```)?$", response_text, re.DOTALL)
        sql = sql_match.group(1).strip() if sql_match else response_text.strip()

        # Ensure SQL ends with semicolon
        sql = sql.rstrip(";").strip() + ";"

        logger.info(f"Fixed SQL: {sql}")

        state["sql"] = sql
        state["retries"] = state["retries"] + 1
        state["iterations"] = state["iterations"] + 1

        return state

    except Exception as e:
        logger.error(f"SQL fix failed: {e}", exc_info=True)
        state["error"] = f"Failed to fix SQL: {str(e)}"
        state["retries"] = state["retries"] + 1
        state["iterations"] = state["iterations"] + 1
        return state
