"""Schema retrieval tools."""

import logging
from typing import Any

import psycopg

from app.config import settings
from app.tools.exceptions import SchemaError

logger = logging.getLogger(__name__)


async def get_schema() -> dict[str, Any]:
    """Retrieve schema information from target database.

    For small schemas (< 20 tables), returns full schema.
    For larger schemas, use embedding search to retrieve relevant tables.

    Returns:
        Dict with table names, columns, types, and foreign keys.

    Raises:
        SchemaError: If schema retrieval fails.
    """
    try:
        async with await psycopg.AsyncConnection.connect(
            settings.target_db_url
        ) as conn:
            async with conn.cursor() as cur:
                # Query information schema
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

    except Exception as e:
        logger.error(f"Schema retrieval failed: {e}", exc_info=True)
        raise SchemaError(f"Failed to retrieve schema: {str(e)}") from e


async def get_table_metadata(table_name: str) -> dict[str, Any]:
    """Retrieve detailed metadata for a specific table.

    Args:
        table_name: Name of the table.

    Returns:
        Dict with columns, sample rows, and statistics.

    Raises:
        SchemaError: If metadata retrieval fails.
    """
    try:
        async with await psycopg.AsyncConnection.connect(
            settings.target_db_url
        ) as conn:
            async with conn.cursor() as cur:
                # Get column information
                query = """
                    SELECT column_name, data_type, is_nullable
                    FROM information_schema.columns
                    WHERE table_schema = 'public' AND table_name = %s
                    ORDER BY ordinal_position;
                """
                await cur.execute(query, (table_name,))
                columns = await cur.fetchall()

                # Get sample data
                sample_query = f"SELECT * FROM {table_name} LIMIT 5;"
                await cur.execute(sample_query)
                sample_rows = await cur.fetchall()

                return {
                    "table_name": table_name,
                    "columns": [
                        {"name": col[0], "type": col[1], "nullable": col[2] == "YES"}
                        for col in columns
                    ],
                    "sample_rows": sample_rows,
                }

    except Exception as e:
        logger.error(
            f"Table metadata retrieval failed for {table_name}: {e}", exc_info=True
        )
        raise SchemaError(
            f"Failed to retrieve metadata for {table_name}: {str(e)}"
        ) from e
