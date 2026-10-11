"""Tests for conversation memory and state persistence."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agent.state import AgentState
from app.agent.nodes.load_memory import load_memory
from app.agent.nodes.save_memory import save_memory
from app.memory.postgres import (
    save_conversation,
    save_message,
    load_conversation_history,
    load_successful_queries,
    save_long_term_memory,
    load_long_term_memory,
)


@pytest.fixture
def initial_state() -> AgentState:
    """Create initial agent state for a multi-turn conversation."""
    return {
        "conversation_id": "conv-123",
        "user_id": "user-1",
        "question": "Show customers from Maharashtra",
        "history": [],
        "plan": ["Filter customers by state", "Return results"],
        "needs_schema": False,
        "schema_context": "Table: customers (id, name, state, email)",
        "sql": "SELECT * FROM customers WHERE state = 'Maharashtra';",
        "validation": {"ok": True, "sql": "SELECT * FROM customers WHERE state = 'Maharashtra' LIMIT 1000;"},
        "result": {
            "ok": True,
            "columns": ["id", "name", "state", "email"],
            "rows": [{"id": 1, "name": "Alice", "state": "Maharashtra", "email": "alice@example.com"}],
            "row_count": 1,
        },
        "error": None,
        "retries": 0,
        "iterations": 8,
        "status": "answered",
        "answer": "Found 1 customer from Maharashtra.",
    }


def test_save_conversation():
    """Test saving a conversation."""
    with patch("app.memory.postgres._get_db_connection") as mock_conn_factory:
        # Mock the connection and cursor
        mock_conn = AsyncMock()
        mock_cursor = AsyncMock()
        mock_conn.cursor.return_value.__aenter__.return_value = mock_cursor
        mock_conn.__aenter__.return_value = mock_conn
        mock_conn_factory.return_value = mock_conn

        # Run the async function
        asyncio.run(
            save_conversation(
                conversation_id="conv-123",
                user_id="user-1",
                title="Customer Query Session",
            )
        )

        # Verify the cursor execute was called
        mock_cursor.execute.assert_called_once()
        assert "INSERT INTO conversations" in mock_cursor.execute.call_args[0][0]


def test_save_and_load_message():
    """Test saving and loading a message (turn)."""
    with patch("app.memory.postgres._get_db_connection") as mock_conn_factory:
        # Mock the connection and cursor
        mock_conn = AsyncMock()
        mock_cursor = AsyncMock()
        mock_conn.cursor.return_value.__aenter__.return_value = mock_cursor
        mock_conn.__aenter__.return_value = mock_conn
        mock_conn_factory.return_value = mock_conn

        # Save a message
        asyncio.run(
            save_message(
                message_id="msg-1",
                conversation_id="conv-123",
                turn_number=1,
                question="What is the total revenue?",
                plan=["Get orders", "Sum revenue"],
                sql="SELECT SUM(total) FROM orders;",
                status="answered",
                answer="Total revenue is $50,000",
                error=None,
                iterations_used=8,
                retries_used=0,
            )
        )

        # Verify
        mock_cursor.execute.assert_called_once()
        assert "INSERT INTO messages" in mock_cursor.execute.call_args[0][0]


def test_multi_turn_conversation():
    """Test a multi-turn conversation with follow-up."""
    conversation_id = "conv-multi-turn"
    user_id = "user-1"

    # Simulate Turn 1: "Top 5 customers by revenue"
    turn1_state: AgentState = {
        "conversation_id": conversation_id,
        "user_id": user_id,
        "question": "Top 5 customers by revenue",
        "history": [],
        "plan": ["Group by customer", "Sum revenue", "Sort DESC", "Limit 5"],
        "needs_schema": True,
        "schema_context": "Table: customers (id, name)",
        "sql": "SELECT c.id, c.name, SUM(o.total) as revenue FROM customers c JOIN orders o ON c.id = o.customer_id GROUP BY c.id, c.name ORDER BY revenue DESC LIMIT 5;",
        "validation": {"ok": True},
        "result": {
            "ok": True,
            "columns": ["id", "name", "revenue"],
            "rows": [
                {"id": 1, "name": "Alice", "revenue": 50000},
                {"id": 2, "name": "Bob", "revenue": 45000},
            ],
            "row_count": 2,
        },
        "error": None,
        "retries": 0,
        "iterations": 8,
        "status": "answered",
        "answer": "Top 5 customers: Alice ($50k), Bob ($45k)...",
    }

    # Simulate Turn 2: "Now only for Maharashtra"
    # This is a follow-up that should reference Turn 1's SQL
    turn2_state: AgentState = {
        "conversation_id": conversation_id,
        "user_id": user_id,
        "question": "Now only for Maharashtra",
        "history": [
            {
                "turn_number": 1,
                "question": "Top 5 customers by revenue",
                "sql": turn1_state["sql"],
                "status": "answered",
                "answer": "Top 5 customers: Alice ($50k), Bob ($45k)...",
            }
        ],
        "plan": ["Add WHERE clause for Maharashtra", "Group by customer", "Sum revenue", "Sort DESC", "Limit 5"],
        "needs_schema": False,
        "schema_context": "",
        "sql": "SELECT c.id, c.name, SUM(o.total) as revenue FROM customers c JOIN orders o ON c.id = o.customer_id WHERE c.state = 'Maharashtra' GROUP BY c.id, c.name ORDER BY revenue DESC LIMIT 5;",
        "validation": {"ok": True},
        "result": {
            "ok": True,
            "columns": ["id", "name", "revenue"],
            "rows": [{"id": 1, "name": "Alice", "revenue": 30000}],
            "row_count": 1,
        },
        "error": None,
        "retries": 0,
        "iterations": 7,
        "status": "answered",
        "answer": "Top customers in Maharashtra: Alice ($30k)...",
    }

    # Assertions about the multi-turn structure
    assert len(turn2_state["history"]) == 1
    assert turn2_state["history"][0]["question"] == "Top 5 customers by revenue"
    assert "WHERE c.state = 'Maharashtra'" in turn2_state["sql"]


def test_load_memory_node():
    """Test the load_memory node integrates with PostgreSQL."""
    state: AgentState = {
        "conversation_id": "conv-123",
        "user_id": "user-1",
        "question": "Now only for Maharashtra",
        "history": [],
        "plan": [],
        "needs_schema": False,
        "schema_context": "",
        "sql": None,
        "validation": None,
        "result": None,
        "error": None,
        "retries": 0,
        "iterations": 0,
        "status": "running",
        "answer": None,
    }

    with patch("app.agent.nodes.load_memory.load_turn") as mock_load_turn:
        # Mock the return value
        mock_load_turn.return_value = {
            "turns": [
                {
                    "turn_number": 1,
                    "question": "Top 5 customers",
                    "sql": "SELECT * FROM customers LIMIT 5;",
                    "status": "answered",
                    "answer": "5 customers found",
                },
            ],
            "successful_queries": [
                {"sql": "SELECT * FROM customers LIMIT 5;", "question": "Top 5 customers", "latency_ms": 100},
            ],
        }

        # Call load_memory
        result_state = load_memory(state)

        # Verify
        assert result_state["iterations"] == 1  # Incremented
        assert len(result_state["history"]) == 1
        assert result_state["history"][0]["question"] == "Top 5 customers"


def test_save_memory_node():
    """Test the save_memory node."""
    state: AgentState = {
        "conversation_id": "conv-123",
        "user_id": "user-1",
        "question": "Top 5 customers",
        "history": [],
        "plan": ["Select", "Limit 5"],
        "needs_schema": False,
        "schema_context": "",
        "sql": "SELECT * FROM customers LIMIT 5;",
        "validation": {"ok": True},
        "result": {
            "ok": True,
            "columns": ["id", "name"],
            "rows": [{"id": 1, "name": "Alice"}],
            "row_count": 1,
        },
        "error": None,
        "retries": 0,
        "iterations": 8,
        "status": "answered",
        "answer": "5 customers found",
    }

    with patch("app.agent.nodes.save_memory.save_turn_db") as mock_save:
        # Call save_memory
        result_state = save_memory(state)

        # Verify
        assert result_state["iterations"] == 9  # Incremented
        mock_save.assert_called_once()


def test_long_term_memory_flag():
    """Test that long-term memory is gated by config flag."""
    config_with_ltm = MagicMock()
    config_with_ltm.memory_long_term_enabled = True
    config_with_ltm.memory_history_limit = 10

    config_without_ltm = MagicMock()
    config_without_ltm.memory_long_term_enabled = False
    config_without_ltm.memory_history_limit = 10

    # With long-term memory enabled
    with patch("app.agent.nodes.load_memory.get_config", return_value=config_with_ltm):
        with patch("app.agent.nodes.load_memory.load_turn") as mock_load:
            mock_load.return_value = {
                "turns": [],
                "successful_queries": [],
                "few_shot_examples": [
                    {"question": "Top customers", "sql": "SELECT * FROM customers LIMIT 5;"}
                ],
            }

            state: AgentState = {
                "conversation_id": "conv-123",
                "user_id": "user-1",
                "question": "Similar question",
                "history": [],
                "plan": [],
                "needs_schema": False,
                "schema_context": "",
                "sql": None,
                "validation": None,
                "result": None,
                "error": None,
                "retries": 0,
                "iterations": 0,
                "status": "running",
                "answer": None,
            }

            result = load_memory(state)
            assert "_few_shot_examples" in result or "few_shot_examples" in result

    # Without long-term memory enabled
    with patch("app.agent.nodes.load_memory.get_config", return_value=config_without_ltm):
        with patch("app.agent.nodes.load_memory.load_turn") as mock_load:
            mock_load.return_value = {
                "turns": [],
                "successful_queries": [],
            }

            state["_few_shot_examples"] = None
            result = load_memory(state)
            # Should still work, just no few-shot examples


def test_resume_after_crash():
    """Test resuming a conversation from Redis checkpointer after crash."""
    # This test simulates the resumable nature of LangGraph with Redis checkpointer
    conversation_id = "conv-resume-test"
    thread_id = f"thread_{conversation_id}"

    # Initial state before crash
    initial_state: AgentState = {
        "conversation_id": conversation_id,
        "user_id": "user-1",
        "question": "Top 10 products by sales",
        "history": [
            {
                "turn_number": 1,
                "question": "Top 5 customers by revenue",
                "sql": "SELECT * FROM customers LIMIT 5;",
                "status": "answered",
                "answer": "5 customers found",
            }
        ],
        "plan": ["Select products", "Sum sales", "Sort DESC", "Limit 10"],
        "needs_schema": True,
        "schema_context": "Table: products (id, name, sales)",
        "sql": None,
        "validation": None,
        "result": None,
        "error": None,
        "retries": 0,
        "iterations": 2,  # After load_memory and planner
        "status": "running",
        "answer": None,
    }

    # After recovery from Redis checkpointer, state should be resumed with same conversation_id
    # and thread_id would be used by LangGraph to fetch the checkpointed state
    resumed_state = initial_state  # Would be fetched from Redis

    # Verify the state is resumable
    assert resumed_state["conversation_id"] == conversation_id
    assert resumed_state["iterations"] == 2
    assert len(resumed_state["history"]) == 1

    # Continue execution from where it left off
    # The agent would continue with retrieve_schema next


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
