"""SQL executor with safety guardrails: timeout, row limits, read-only mode."""

import asyncio
import logging
from typing import Any

import psycopg

from app.config import settings
from app.tools.exceptions import ExecutionError, TimeoutError, RowLimitExceeded

logger = logging.getLogger(__name__)


async def execute_sql(sql: str, timeout_seconds: int | None = None) -> dict[str, Any]:
    """Execute SQL query against target database with safety guardrails.

    Args:
        sql: Validated SQL query.
        timeout_seconds: Query timeout in seconds (defaults to config setting).

    Returns:
        Dict with keys: columns, rows, row_count.

    Raises:
        ExecutionError: If execution fails.
        TimeoutError: If query times out.
        RowLimitExceeded: If result exceeds row limit.
    """
    if timeout_seconds is None:
        timeout_seconds = settings.query_timeout_seconds

    try:
        async with await psycopg.AsyncConnection.connect(
            settings.target_db_url, autocommit=False
        ) as conn:
            # Enforce read-only transaction
            async with conn.cursor() as cur:
                await cur.execute("SET TRANSACTION READ ONLY;")
                await cur.execute(f"SET statement_timeout = {timeout_seconds * 1000};")

                try:
                    await asyncio.wait_for(
                        cur.execute(sql), timeout=timeout_seconds + 1
                    )
                except asyncio.TimeoutError as e:
                    raise TimeoutError(
                        f"Query exceeded {timeout_seconds}s timeout"
                    ) from e

                # Fetch results with row limit
                rows = await cur.fetchall()
                if len(rows) >= settings.result_row_limit:
                    raise RowLimitExceeded(
                        f"Result exceeds {settings.result_row_limit} row limit"
                    )

                columns = [desc[0] for desc in cur.description] if cur.description else []

                return {
                    "columns": columns,
                    "rows": [dict(zip(columns, row)) for row in rows],
                    "row_count": len(rows),
                }

    except (TimeoutError, RowLimitExceeded):
        raise
    except Exception as e:
        logger.error(f"SQL execution failed: {e}", exc_info=True)
        raise ExecutionError(f"Execution failed: {str(e)}") from e
