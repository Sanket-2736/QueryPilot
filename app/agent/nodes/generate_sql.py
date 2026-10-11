"""Generate SQL from plan and schema."""

import logging
import re
from typing import Any

from langchain_openai import ChatOpenAI

from app.agent.state import AgentState
from app.config import get_config

logger = logging.getLogger(__name__)


def generate_sql(state: AgentState) -> dict[str, Any]:
    """Generate SQL from the plan and schema.

    Uses few-shot examples from long-term memory if available.

    Args:
        state: Current agent state.

    Returns:
        Updated state with sql populated.
    """
    logger.info("Generating SQL")
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
        with open("app/prompts/generate_sql.txt", "r") as f:
            prompt_template = f.read()

        # Build full prompt
        plan_text = "\n".join([f"  {i + 1}. {step}" for i, step in enumerate(state["plan"])])
        history_text = ""
        
        if state.get("history"):
            history_text = "Recent successful queries from this conversation:\n"
            for h in state["history"][-2:]:  # Last 2 turns
                if h.get("sql"):
                    history_text += f"  Q: {h.get('question', '')}\n"
                    history_text += f"  SQL: {h['sql']}\n\n"

        # Add few-shot examples if long-term memory is enabled
        few_shot_text = ""
        if config.memory_long_term_enabled and state.get("few_shot_examples"):
            few_shot_text = "Few-shot examples from similar past queries:\n"
            for i, example in enumerate(state["few_shot_examples"], 1):
                few_shot_text += f"{i}. Q: {example.get('question', '')}\n"
                few_shot_text += f"   SQL: {example.get('sql', '')}\n\n"

        full_prompt = (
            f"{prompt_template}\n\n"
            f"Question: {state['question']}\n\n"
            f"Plan:\n{plan_text}\n\n"
            f"Schema:\n{state['schema_context']}\n\n"
            f"{few_shot_text}"
            f"{history_text}"
        )

        response = llm.invoke(full_prompt)
        response_text = response.content

        # Extract SQL from response (it may be wrapped in markdown code blocks)
        sql_match = re.search(r"(?:```sql\n)?(.*?)(?:\n```)?$", response_text, re.DOTALL)
        sql = sql_match.group(1).strip() if sql_match else response_text.strip()

        # Ensure SQL ends with semicolon
        sql = sql.rstrip(";").strip() + ";"

        logger.info(f"Generated SQL: {sql}")

        state["sql"] = sql
        state["iterations"] = state["iterations"] + 1

        return state

    except Exception as e:
        logger.error(f"SQL generation failed: {e}", exc_info=True)
        state["error"] = f"Failed to generate SQL: {str(e)}"
        state["status"] = "failed"
        state["iterations"] = state["iterations"] + 1
        return state
