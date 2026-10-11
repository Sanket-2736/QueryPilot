"""Graph-level tests with mocked LLM responses."""

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.agent.graph import MAX_ITERATIONS, MAX_RETRIES, compile_graph
from app.agent.state import AgentState


class FakeLLMResponse:
    """Fake LLM response."""

    def __init__(self, content: str):
        """Initialize with response content."""
        self.content = content


class FakeLLM:
    """Fake LLM for testing."""

    def __init__(self, responses: dict[str, Any]):
        """Initialize with response templates."""
        self.responses = responses
        self.call_count = {}

    def invoke(self, prompt: str) -> FakeLLMResponse:
        """Simulate LLM invocation."""
        # Detect which node this is for based on prompt content
        node_type = self._detect_node_type(prompt)
        response_key = node_type
        self.call_count[response_key] = self.call_count.get(response_key, 0) + 1

        if response_key not in self.responses:
            # Return a default error response
            return FakeLLMResponse(json.dumps({
                "plan": [],
                "needs_schema": False,
                "ambiguity_flag": False,
                "clarifying_question": ""
            }))

        response_value = self.responses[response_key]
        if isinstance(response_value, str):
            return FakeLLMResponse(response_value)
        else:
            return FakeLLMResponse(json.dumps(response_value))

    def _detect_node_type(self, prompt: str) -> str:
        """Detect which node is calling based on prompt content."""
        if "Break the question into" in prompt or "task decomposition" in prompt:
            return "planner"
        elif "Generate a valid PostgreSQL" in prompt or "given question and database schemas" in prompt:
            return "generate_sql"
        elif "fix broken SQL" in prompt or "error and produce corrected SQL" in prompt:
            return "fix_sql"
        elif "summarizing database query results" in prompt or "summarize database query" in prompt:
            return "analyze_result"
        else:
            return "unknown"


@pytest.fixture
def initial_state() -> AgentState:
    """Create initial agent state."""
    return {
        "conversation_id": "test-conv-1",
        "user_id": "user-1",
        "question": "What are the top 5 customers by spending?",
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


def test_happy_path(initial_state: AgentState):
    """Test happy path: planner -> schema -> generate -> validate -> execute -> analyze -> final."""
    fake_llm = FakeLLM(
        {
            "planner": {
                "plan": [
                    "Find the orders and customers tables",
                    "Sum total spending per customer",
                    "Order by spending descending",
                    "Limit to top 5"
                ],
                "needs_schema": True,
                "ambiguity_flag": False,
                "clarifying_question": ""
            },
            "generate_sql": "SELECT c.id, c.name, SUM(o.total) as total FROM customers c LEFT JOIN orders o ON c.id = o.customer_id GROUP BY c.id, c.name ORDER BY total DESC LIMIT 5;",
            "analyze_result": "The top 5 customers by spending are shown above."
        }
    )

    with patch("app.agent.nodes.planner.ChatOpenAI") as mock_llm_class, \
         patch("app.agent.nodes.retrieve_schema.asyncio.run") as mock_async_run, \
         patch("app.agent.nodes.generate_sql.ChatOpenAI") as mock_gen_llm, \
         patch("app.agent.nodes.execute_sql.asyncio.run") as mock_exec_run, \
         patch("app.agent.nodes.analyze_result.ChatOpenAI") as mock_analyze_llm:

        # Mock LLM calls
        mock_llm_class.return_value = fake_llm
        mock_gen_llm.return_value = fake_llm
        mock_analyze_llm.return_value = fake_llm

        # Mock schema retrieval
        mock_async_run.side_effect = [
            {"customers": {"columns": []}, "orders": {"columns": []}},  # Schema retrieval
            {"ok": True, "columns": ["id", "name", "total"], "rows": [
                {"id": 1, "name": "Alice", "total": 15000},
                {"id": 2, "name": "Bob", "total": 12000}
            ], "row_count": 2}  # Execution
        ]

        # Run graph
        agent = compile_graph()
        final_state = agent.invoke(initial_state)

        # Assertions
        assert final_state["status"] == "answered"
        assert final_state["answer"] is not None
        assert final_state["sql"] is not None
        assert final_state["iterations"] >= 8
        assert final_state["retries"] == 0


def test_invalid_sql_then_fix(initial_state: AgentState):
    """Test: invalid SQL then successful fix."""
    fake_llm = FakeLLM(
        {
            "planner": {
                "plan": ["Get customers"],
                "needs_schema": False,
                "ambiguity_flag": False,
                "clarifying_question": ""
            },
            "generate_sql": "SELECT * FROM invalid_table;",  # Will fail validation
            "fix_sql": "SELECT id, name FROM customers LIMIT 1000;",  # Fixed version
            "analyze_result": "Here are the customers."
        }
    )

    with patch("app.agent.nodes.planner.ChatOpenAI") as mock_llm_class, \
         patch("app.agent.nodes.generate_sql.ChatOpenAI") as mock_gen_llm, \
         patch("app.agent.nodes.fix_sql.ChatOpenAI") as mock_fix_llm, \
         patch("app.agent.nodes.execute_sql.asyncio.run") as mock_exec_run, \
         patch("app.agent.nodes.analyze_result.ChatOpenAI") as mock_analyze_llm:

        mock_llm_class.return_value = fake_llm
        mock_gen_llm.return_value = fake_llm
        mock_fix_llm.return_value = fake_llm
        mock_analyze_llm.return_value = fake_llm

        # Mock execution result
        mock_exec_run.return_value = {
            "ok": True,
            "columns": ["id", "name"],
            "rows": [{"id": 1, "name": "Alice"}],
            "row_count": 1
        }

        agent = compile_graph()
        final_state = agent.invoke(initial_state)

        # Assertions
        assert final_state["status"] == "answered"
        assert final_state["retries"] == 1  # One fix attempt


def test_destructive_sql_rejected(initial_state: AgentState):
    """Test: destructive SQL ends rejected."""
    fake_llm = FakeLLM(
        {
            "planner": {
                "plan": ["Get customers"],
                "needs_schema": False,
                "ambiguity_flag": False,
                "clarifying_question": ""
            },
            "generate_sql": "DELETE FROM customers WHERE id = 1;",  # Destructive!
        }
    )

    with patch("app.agent.nodes.planner.ChatOpenAI") as mock_llm_class, \
         patch("app.agent.nodes.generate_sql.ChatOpenAI") as mock_gen_llm:

        mock_llm_class.return_value = fake_llm
        mock_gen_llm.return_value = fake_llm

        agent = compile_graph()
        final_state = agent.invoke(initial_state)

        # Assertions
        assert final_state["status"] == "rejected"
        assert "not allowed" in final_state["answer"].lower()


def test_retries_exhausted_ends_failed(initial_state: AgentState):
    """Test: retries exhausted ends failed."""
    fake_llm = FakeLLM(
        {
            "planner": {
                "plan": ["Get data"],
                "needs_schema": False,
                "ambiguity_flag": False,
                "clarifying_question": ""
            },
            "generate_sql": "SELECT * FROM customers LIMIT 1000;",
            "fix_sql": "SELECT * FROM unknown_table_xyz LIMIT 1000;"  # Always generates invalid SQL
        }
    )

    with patch("app.agent.nodes.planner.ChatOpenAI") as mock_llm_class, \
         patch("app.agent.nodes.generate_sql.ChatOpenAI") as mock_gen_llm, \
         patch("app.agent.nodes.fix_sql.ChatOpenAI") as mock_fix_llm:

        mock_llm_class.return_value = fake_llm
        mock_gen_llm.return_value = fake_llm
        mock_fix_llm.return_value = fake_llm

        agent = compile_graph()
        final_state = agent.invoke(initial_state)

        # Assertions
        assert final_state["status"] == "failed"
        assert final_state["retries"] >= MAX_RETRIES


def test_ambiguous_question_asks_clarification(initial_state: AgentState):
    """Test: ambiguous question asks for clarification."""
    fake_llm = FakeLLM(
        {
            "planner": {
                "plan": [],
                "needs_schema": False,
                "ambiguity_flag": True,
                "clarifying_question": "Do you want revenue for this month or this year?"
            },
        }
    )

    with patch("app.agent.nodes.planner.ChatOpenAI") as mock_llm_class:
        mock_llm_class.return_value = fake_llm

        agent = compile_graph()
        final_state = agent.invoke(initial_state)

        # Assertions
        assert final_state["status"] == "needs_clarification"
        assert "month" in final_state["answer"] or "year" in final_state["answer"]


def test_iteration_budget_respected(initial_state: AgentState):
    """Test: iteration budget is respected."""
    # Create a state that has already done MAX_ITERATIONS - 1 iterations
    initial_state["iterations"] = MAX_ITERATIONS - 1

    fake_llm = FakeLLM(
        {
            "planner": {
                "plan": ["Get data"],
                "needs_schema": False,
                "ambiguity_flag": False,
                "clarifying_question": ""
            },
        }
    )

    with patch("app.agent.nodes.planner.ChatOpenAI") as mock_llm_class:
        mock_llm_class.return_value = fake_llm

        agent = compile_graph()
        final_state = agent.invoke(initial_state)

        # Assertions
        assert final_state["iterations"] >= MAX_ITERATIONS
        assert final_state["status"] == "failed"  # Should fail due to budget exhaustion


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
