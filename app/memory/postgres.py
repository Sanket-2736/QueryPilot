"""PostgreSQL-backed memory for conversations and query logs."""

import asyncio
import json
import logging
import time
import uuid
from datetime import datetime
from typing import Any, Optional

import psycopg

from app.agent.state import AgentState
from app.config import get_config
from app.tools.exceptions import QueryPilotException

logger = logging.getLogger(__name__)


class MemoryConnectionError(QueryPilotException):
    """Raised when memory database operations fail."""

    pass


async def _get_db_connection(db_url: str) -> psycopg.AsyncConnection:
    """Get an async database connection."""
    try:
        return await psycopg.AsyncConnection.connect(db_url)
    except Exception as e:
        logger.error(f"Failed to connect to database: {e}", exc_info=True)
        raise MemoryConnectionError(f"Database connection failed: {str(e)}") from e


async def save_conversation(
    conversation_id: str,
    user_id: str,
    title: Optional[str] = None,
) -> None:
    """Save or update a conversation record."""
    config = get_config()
    query = """
        INSERT INTO conversations (id, user_id, title, created_at, updated_at)
        VALUES (%s, %s, %s, NOW(), NOW())
        ON CONFLICT (id) DO UPDATE
        SET updated_at = NOW(), title = COALESCE(EXCLUDED.title, conversations.title)
    """

    try:
        async with await _get_db_connection(config.app_db_url) as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, (conversation_id, user_id, title))
                await conn.commit()
    except MemoryConnectionError:
        raise
    except Exception as e:
        logger.error(f"Failed to save conversation: {e}", exc_info=True)
        raise MemoryConnectionError(f"Failed to save conversation: {str(e)}") from e


async def save_message(
    message_id: str,
    conversation_id: str,
    turn_number: int,
    question: str,
    plan: Optional[list[str]],
    sql: Optional[str],
    status: str,
    answer: Optional[str],
    error: Optional[str],
    iterations_used: int,
    retries_used: int,
) -> None:
    """Save a message (turn) record."""
    config = get_config()
    query = """
        INSERT INTO messages
        (id, conversation_id, turn_number, question, plan, sql, status, answer, error, iterations_used, retries_used, created_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
        ON CONFLICT (id) DO UPDATE
        SET status = EXCLUDED.status, answer = EXCLUDED.answer, error = EXCLUDED.error
    """

    try:
        async with await _get_db_connection(config.app_db_url) as conn:
            async with conn.cursor() as cur:
                plan_json = json.dumps(plan) if plan else None
                await cur.execute(
                    query,
                    (message_id, conversation_id, turn_number, question, plan_json, sql, status, answer, error, iterations_used, retries_used),
                )
                await conn.commit()
    except MemoryConnectionError:
        raise
    except Exception as e:
        logger.error(f"Failed to save message: {e}", exc_info=True)
        raise MemoryConnectionError(f"Failed to save message: {str(e)}") from e


async def save_query_log(
    query_log_id: str,
    message_id: Optional[str],
    conversation_id: str,
    sql: str,
    result_summary: Optional[dict[str, Any]],
    success: bool,
    error: Optional[str],
    latency_ms: int,
    tokens_used: Optional[int],
    cost_cents: Optional[float],
) -> None:
    """Save a query log entry."""
    config = get_config()
    query = """
        INSERT INTO query_log
        (id, message_id, conversation_id, sql, result_summary, success, error, latency_ms, tokens_used, cost_cents, created_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
    """

    try:
        async with await _get_db_connection(config.app_db_url) as conn:
            async with conn.cursor() as cur:
                result_json = json.dumps(result_summary) if result_summary else None
                await cur.execute(
                    query,
                    (query_log_id, message_id, conversation_id, sql, result_json, success, error, latency_ms, tokens_used, cost_cents),
                )
                await conn.commit()
    except MemoryConnectionError:
        raise
    except Exception as e:
        logger.error(f"Failed to save query log: {e}", exc_info=True)
        raise MemoryConnectionError(f"Failed to save query log: {str(e)}") from e


async def load_conversation_history(
    conversation_id: str,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Load recent messages (turns) from a conversation."""
    config = get_config()
    query = """
        SELECT id, turn_number, question, plan, sql, status, answer, error, iterations_used, retries_used, created_at
        FROM messages
        WHERE conversation_id = %s
        ORDER BY turn_number DESC
        LIMIT %s
    """

    try:
        async with await _get_db_connection(config.app_db_url) as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, (conversation_id, limit))
                rows = await cur.fetchall()

                messages = []
                for row in rows:
                    plan = json.loads(row[3]) if row[3] else None
                    messages.append({
                        "id": row[0],
                        "turn_number": row[1],
                        "question": row[2],
                        "plan": plan,
                        "sql": row[4],
                        "status": row[5],
                        "answer": row[6],
                        "error": row[7],
                        "iterations_used": row[8],
                        "retries_used": row[9],
                        "created_at": row[10],
                    })

                # Reverse to oldest first
                return list(reversed(messages))

    except MemoryConnectionError:
        raise
    except Exception as e:
        logger.error(f"Failed to load conversation history: {e}", exc_info=True)
        raise MemoryConnectionError(f"Failed to load conversation history: {str(e)}") from e


async def load_successful_queries(
    conversation_id: str,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Load successful SQL queries from a conversation."""
    config = get_config()
    query = """
        SELECT sql, question, latency_ms
        FROM query_log
        WHERE conversation_id = %s AND success = true
        ORDER BY created_at DESC
        LIMIT %s
    """

    try:
        async with await _get_db_connection(config.app_db_url) as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, (conversation_id, limit))
                rows = await cur.fetchall()

                return [
                    {"sql": row[0], "question": row[1], "latency_ms": row[2]}
                    for row in rows
                ]

    except MemoryConnectionError:
        raise
    except Exception as e:
        logger.error(f"Failed to load successful queries: {e}", exc_info=True)
        raise MemoryConnectionError(f"Failed to load successful queries: {str(e)}") from e


async def save_long_term_memory(
    conversation_id: str,
    question: str,
    sql: str,
    category: Optional[str] = None,
    embedding: Optional[bytes] = None,
) -> None:
    """Save a successful question-SQL pair to long-term memory."""
    config = get_config()
    memory_id = str(uuid.uuid4())
    query = """
        INSERT INTO long_term_memory
        (id, conversation_id, question, sql, embedding, category, success_rate, usage_count, created_at, updated_at)
        VALUES (%s, %s, %s, %s, %s, %s, 1.0, 1, NOW(), NOW())
        ON CONFLICT DO NOTHING
    """

    try:
        async with await _get_db_connection(config.app_db_url) as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    query,
                    (memory_id, conversation_id, question, sql, embedding, category),
                )
                await conn.commit()
    except MemoryConnectionError:
        raise
    except Exception as e:
        logger.error(f"Failed to save long-term memory: {e}", exc_info=True)
        raise MemoryConnectionError(f"Failed to save long-term memory: {str(e)}") from e


async def load_long_term_memory(
    conversation_id: str,
    limit: int = 3,
) -> list[dict[str, Any]]:
    """Load long-term memory entries (few-shot examples) for a conversation."""
    config = get_config()
    query = """
        SELECT question, sql, category, success_rate, usage_count
        FROM long_term_memory
        WHERE conversation_id = %s
        ORDER BY success_rate DESC, usage_count DESC, updated_at DESC
        LIMIT %s
    """

    try:
        async with await _get_db_connection(config.app_db_url) as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, (conversation_id, limit))
                rows = await cur.fetchall()

                return [
                    {
                        "question": row[0],
                        "sql": row[1],
                        "category": row[2],
                        "success_rate": row[3],
                        "usage_count": row[4],
                    }
                    for row in rows
                ]

    except MemoryConnectionError:
        raise
    except Exception as e:
        logger.error(f"Failed to load long-term memory: {e}", exc_info=True)
        raise MemoryConnectionError(f"Failed to load long-term memory: {str(e)}") from e


async def save_turn(
    state: AgentState,
    turn_number: int,
    tokens_used: Optional[int] = None,
    cost_cents: Optional[float] = None,
) -> None:
    """Save a complete turn to memory."""
    message_id = str(uuid.uuid4())
    query_log_id = str(uuid.uuid4())

    # Save conversation
    await save_conversation(state["conversation_id"], state["user_id"])

    # Save message
    await save_message(
        message_id=message_id,
        conversation_id=state["conversation_id"],
        turn_number=turn_number,
        question=state["question"],
        plan=state.get("plan"),
        sql=state.get("sql"),
        status=state["status"],
        answer=state.get("answer"),
        error=state.get("error"),
        iterations_used=state["iterations"],
        retries_used=state["retries"],
    )

    # Save query log if SQL was executed
    if state.get("sql") and state.get("result"):
        latency_ms = int((time.time() % 1) * 1000)  # Placeholder
        result = state["result"]
        result_summary = {
            "columns": result.get("columns", []),
            "row_count": result.get("row_count", 0),
            "sample_rows": result.get("rows", [])[:3],
        } if result.get("ok") else None

        await save_query_log(
            query_log_id=query_log_id,
            message_id=message_id,
            conversation_id=state["conversation_id"],
            sql=state["sql"],
            result_summary=result_summary,
            success=result.get("ok", False),
            error=result.get("error"),
            latency_ms=latency_ms,
            tokens_used=tokens_used,
            cost_cents=cost_cents,
        )

    # Save to long-term memory if successful
    config = get_config()
    if config.memory_long_term_enabled and state.get("status") == "answered" and state.get("sql"):
        await save_long_term_memory(
            conversation_id=state["conversation_id"],
            question=state["question"],
            sql=state["sql"],
        )


async def load_turn(
    conversation_id: str,
    limit: int = 10,
) -> dict[str, Any]:
    """Load turns for a conversation into state.history format."""
    config = get_config()
    history = await load_conversation_history(conversation_id, limit=limit)
    successful_queries = await load_successful_queries(conversation_id, limit=5)

    result = {
        "turns": history,
        "successful_queries": successful_queries,
    }

    # Load long-term memory if enabled
    if config.memory_long_term_enabled:
        long_term = await load_long_term_memory(conversation_id, limit=3)
        result["few_shot_examples"] = long_term

    return result
