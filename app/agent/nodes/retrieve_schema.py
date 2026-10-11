"""Retrieve relevant schema information."""

import asyncio
import logging
from typing import Any

import psycopg

from app.agent.state import AgentState
from app.config import get_config

logger = logging.getLogger(__name__)


async def _get_schema_async(target_db_url: str) -> dict[str, Any]:
    """Fetch schema from target database."""
    async with await psycopg.AsyncConnection.connect(target_db_url) as conn:
        async with conn.cursor() as cur:
            query = """
                SELECT table_name, column_name, data_type, is_nullable
                FROM information_schema.columns
                WHERE table_schema = 'public'
                ORDER BY table_name, ordinal_position;
            """
            await cur.execute(query)
            rows = await cur.fetchall()

            schema: dict[str, Any] = {}
            for table_name, column_name, data_type, is_nullable in rows:
                if table_name not in schema:
                    schema[table_name] = {"columns": []}
                schema[table_name]["columns"].append(
                    {
                        "name": column_name,
                        "type": data_type,
                        "nullable": is_nullable == "YES",
                    }
                )

            return schema


def retrieve_schema(state: AgentState) -> dict[str, Any]:
    """Retrieve schema from target database.

    Args:
        state: Current agent state.

    Returns:
        Updated state with schema_context populated.
    """
    logger.info("Retrieving schema")
    config = get_config()

    try:
        # Run async function
        schema = asyncio.run(_get_schema_async(config.target_db_url))

        # Format as readable schema context
        schema_text = "Database Schema:\n"
        for table_name, table_info in sorted(schema.items()):
            schema_text += f"\nTable: {table_name}\n"
            schema_text += "  Columns:\n"
            for col in table_info["columns"]:
                nullable = "nullable" if col["nullable"] else "NOT NULL"
                schema_text += f"    - {col['name']} ({col['type']}) {nullable}\n"

        state["schema_context"] = schema_text
        state["iterations"] = state["iterations"] + 1

        return state

    except Exception as e:
        logger.error(f"Schema retrieval failed: {e}", exc_info=True)
        state["error"] = f"Failed to retrieve schema: {str(e)}"
        state["status"] = "failed"
        state["iterations"] = state["iterations"] + 1
        return state
