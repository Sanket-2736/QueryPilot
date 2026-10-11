"""Execute SQL against target database (deterministic, no LLM)."""

import asyncio
import logging
from typing import Any

import psycopg

from app.agent.state import AgentState
from app.config import get_config

logger = logging.getLogger(__name__)


async def _execute_sql_async(
    sql: str, target_db_url: str, timeout_seconds: int, row_limit: int
) -> dict[str, Any]:
    """Execute SQL asynchronously."""
    try:
        async with await psycopg.AsyncConnection.connect(
            target_db_url, autocommit=False
        ) as conn:
            async with conn.cursor() as cur:
                # Enforce read-only transaction
                await cur.execute("SET TRANSACTION READ ONLY;")
                await cur.execute(f"SET statement_timeout = {timeout_seconds * 1000};")

                try:
                    await asyncio.wait_for(cur.execute(sql), timeout=timeout_seconds + 1)
                except asyncio.TimeoutError as e:
                    return {
                        "ok": False,
                        "error": f"Query timed out after {timeout_seconds} seconds",
                    }

                # Fetch results
                rows = await cur.fetchall()
                columns = [desc[0] for desc in cur.description] if cur.description else []

                # Check row limit
                if len(rows) >= row_limit:
                    return {
                        "ok": False,
                        "error": f"Result exceeds {row_limit} row limit; truncated.",
                        "columns": columns,
                        "rows": [dict(zip(columns, row)) for row in rows[:row_limit]],
                        "row_count": len(rows),
                    }

                return {
                    "ok": True,
                    "columns": columns,
                    "rows": [dict(zip(columns, row)) for row in rows],
                    "row_count": len(rows),
                }

    except Exception as e:
        logger.error(f"SQL execution error: {e}", exc_info=True)
        return {"ok": False, "error": f"Execution failed: {str(e)}"}


def execute_sql(state: AgentState) -> dict[str, Any]:
    """Execute SQL against target database.

    Args:
        state: Current agent state.

    Returns:
        Updated state with result populated.
    """
    logger.info("Executing SQL")
    config = get_config()

    if not state.get("sql"):
        state["result"] = {"ok": False, "error": "no_sql_to_execute"}
        state["iterations"] = state["iterations"] + 1
        return state

    try:
        # Run async execution
        result = asyncio.run(
            _execute_sql_async(
                state["sql"],
                config.target_db_url,
                config.query_timeout_seconds,
                config.result_row_limit,
            )
        )

        state["result"] = result

        if not result.get("ok"):
            state["error"] = result.get("error", "Unknown execution error")

        state["iterations"] = state["iterations"] + 1

        return state

    except Exception as e:
        logger.error(f"Execution wrapper error: {e}", exc_info=True)
        state["result"] = {"ok": False, "error": f"Execution failed: {str(e)}"}
        state["error"] = str(e)
        state["iterations"] = state["iterations"] + 1
        return state
