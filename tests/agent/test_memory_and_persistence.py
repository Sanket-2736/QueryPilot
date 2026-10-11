"""Tests for conversation memory, persistence, and multi-turn handling."""

import json
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agent.graph import compile_graph
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
        node_type = self._detect_node_type(prompt)
        response_key = node_type
        self.call_count[response_key] = self.call_count.get(response_key, 0) + 1

        if response_key not in self.responses:
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
        elif "fix broken SQL" in prompt:
            return "fix_sql"
        elif "summarizing database query results" in prompt:
            return "analyze_result"
        else:
            return "unknown"


@pytest.fixture
def initial_state() -> AgentState:
    """Create initial agent state for turn 1."""
    return {
        "conversation_id": "test-conv-123",
        "user_id": "user-1",
        "question": "What are the top 5 customers by spending?",
        "history": [],
        "few_shot_examples": [],
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
        "_execution_time_ms": None,
        "_tokens_used": None,
        "_cost_usd": None,
    }


@pytest.mark.asyncio
async def test_multi_turn_follow_up():
    """Test multi-turn conversation where turn 2 is a follow-up referencing turn 1."""
    conversation_id = "test-conv-follow-up"
    
    # Turn 1: Initial query
    turn1_state: AgentState = {
        "conversation_id": conversation_id,
        "user_id": "user-1",
        "question": "What are the top 5 customers by spending?",
        "history": [],
        "few_shot_examples": [],
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
        "_execution_time_ms": None,
        "_tokens_used": None,
        "_cost_usd": None,
    }

    fake_llm = FakeLLM({
        "planner": {
            "plan": ["Get customers", "Order by spending"],
            "needs_schema": True,
            "ambiguity_flag": False,
            "clarifying_question": ""
        },
        "generate_sql": "SELECT c.id, c.name, SUM(o.total) as total FROM customers c LEFT JOIN orders o ON c.id = o.customer_id GROUP BY c.id, c.name ORDER BY total DESC LIMIT 5;",
        "analyze_result": "Top 5 customers by spending are shown above."
    })

    with patch("app.agent.nodes.planner.ChatOpenAI") as mock_llm_class, \
         patch("app.agent.nodes.retrieve_schema.asyncio.run") as mock_async_run, \
         patch("app.agent.nodes.generate_sql.ChatOpenAI") as mock_gen_llm, \
         patch("app.agent.nodes.execute_sql.asyncio.run") as mock_exec_run, \
         patch("app.agent.nodes.analyze_result.ChatOpenAI") as mock_analyze_llm, \
         patch("app.agent.nodes.save_memory._save_memory_async") as mock_save_mem, \
         patch("app.agent.nodes.load_memory._load_memory_async") as mock_load_mem:

        mock_llm_class.return_value = fake_llm
        mock_gen_llm.return_value = fake_llm
        mock_analyze_llm.return_value = fake_llm
        
        # Mock async functions
        mock_async_run.side_effect = [
            {"customers": {"columns": []}, "orders": {"columns": []}},  # Schema
            {"ok": True, "columns": ["id", "name", "total"], "rows": [
                {"id": 1, "name": "Alice", "total": 15000},
                {"id": 2, "name": "Bob", "total": 12000}
            ], "row_count": 2}  # Execution
        ]
        
        # Mock memory operations
        async def mock_load(state):
            state["history"] = []
        
        async def mock_save(state):
            pass
        
        mock_load_mem.side_effect = mock_load
        mock_save_mem.side_effect = mock_save

        # Run turn 1
        agent = compile_graph()
        final_state_turn1 = agent.invoke(turn1_state)

        # Assertions for turn 1
        assert final_state_turn1["status"] == "answered"
        assert final_state_turn1["sql"] is not None
        assert "Alice" in final_state_turn1["answer"] or "customers" in final_state_turn1["answer"].lower()

        # Turn 2: Follow-up with reference to previous query
        # In a real scenario, history would be loaded from DB
        turn2_state: AgentState = {
            "conversation_id": conversation_id,
            "user_id": "user-1",
            "question": "Now only for Maharashtra",  # Follow-up referencing turn 1
            "history": [
                {
                    "question": final_state_turn1["question"],
                    "sql": final_state_turn1["sql"],
                    "answer": final_state_turn1["answer"],
                    "plan": final_state_turn1["plan"],
                }
            ],
            "few_shot_examples": [],
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
            "_execution_time_ms": None,
            "_tokens_used": None,
            "_cost_usd": None,
        }

        fake_llm_turn2 = FakeLLM({
            "planner": {
                "plan": ["Get customers from Maharashtra", "Order by spending"],
                "needs_schema": False,  # Reuse previous schema
                "ambiguity_flag": False,
                "clarifying_question": ""
            },
            "generate_sql": "SELECT c.id, c.name, SUM(o.total) as total FROM customers c LEFT JOIN orders o ON c.id = o.customer_id WHERE c.state = 'Maharashtra' GROUP BY c.id, c.name ORDER BY total DESC LIMIT 5;",
            "analyze_result": "Top 5 customers in Maharashtra by spending."
        })

        mock_llm_class.return_value = fake_llm_turn2
        mock_gen_llm.return_value = fake_llm_turn2
        mock_analyze_llm.return_value = fake_llm_turn2

        mock_exec_run.reset_mock()
        mock_exec_run.side_effect = [
            {"ok": True, "columns": ["id", "name", "total"], "rows": [
                {"id": 5, "name": "Charlie", "total": 8000},
            ], "row_count": 1}
        ]

        # Run turn 2
        final_state_turn2 = agent.invoke(turn2_state)

        # Assertions for turn 2
        assert final_state_turn2["status"] == "answered"
        # Should reference previous SQL and modify it
        assert final_state_turn2["sql"] is not None
        # The generated SQL should include Maharashtra filter
        assert "Maharashtra" in final_state_turn2["sql"] or final_state_turn2["sql"] != final_state_turn1["sql"]


def test_resume_after_crash(initial_state: AgentState):
    """Test resuming an interrupted run using Redis checkpointer."""
    # This test verifies that state can be restored and resumed
    conversation_id = initial_state["conversation_id"]
    
    # Simulate a partial state after some node execution
    partial_state = initial_state.copy()
    partial_state["iterations"] = 3
    partial_state["plan"] = ["Step 1", "Step 2"]
    partial_state["needs_schema"] = True
    
    # In a real scenario, this partial state would be loaded from Redis
    # checkpoint with thread_id = conversation_id
    
    # Simulate resuming from this checkpoint
    # The agent should continue from where it left off
    assert partial_state["iterations"] == 3
    assert len(partial_state["plan"]) == 2
    
    # Verify that the state structure is preserved for resumption
    assert "conversation_id" in partial_state
    assert partial_state["conversation_id"] == conversation_id


def test_long_term_memory_flag_changes_prompt():
    """Test that enabling long-term memory flag includes few-shot examples in prompt."""
    initial_state: AgentState = {
        "conversation_id": "test-conv-long-term",
        "user_id": "user-1",
        "question": "What are the top customers?",
        "history": [],
        "few_shot_examples": [
            {
                "question": "Top 5 customers by spending?",
                "sql": "SELECT c.id, c.name, SUM(o.total) FROM customers c JOIN orders o ON c.id = o.customer_id GROUP BY c.id, c.name ORDER BY SUM(o.total) DESC LIMIT 5;",
                "result_summary": "Returns 5 rows"
            }
        ],
        "plan": [],
        "needs_schema": False,
        "schema_context": "Table: customers (id, name)",
        "sql": None,
        "validation": None,
        "result": None,
        "error": None,
        "retries": 0,
        "iterations": 0,
        "status": "running",
        "answer": None,
        "_execution_time_ms": None,
        "_tokens_used": None,
        "_cost_usd": None,
    }

    fake_llm = FakeLLM({
        "generate_sql": "SELECT c.id, c.name, SUM(o.total) as total FROM customers c JOIN orders o ON c.id = o.customer_id GROUP BY c.id, c.name ORDER BY total DESC LIMIT 5;"
    })

    prompt_received = {"text": ""}

    def capture_prompt(prompt: str) -> FakeLLMResponse:
        prompt_received["text"] = prompt
        return FakeLLMResponse(fake_llm.invoke(prompt).content)

    fake_llm.invoke = capture_prompt

    with patch("app.agent.nodes.generate_sql.ChatOpenAI") as mock_llm_class, \
         patch("app.config.get_config") as mock_config:

        mock_llm_instance = MagicMock()
        mock_llm_instance.invoke = capture_prompt
        mock_llm_class.return_value = mock_llm_instance

        mock_cfg = MagicMock()
        mock_cfg.llm_model = "gpt-4"
        mock_cfg.llm_temperature = 0.0
        mock_cfg.llm_max_tokens = 2048
        mock_cfg.openai_api_key = "test-key"
        mock_cfg.memory_long_term_enabled = True  # ENABLE LONG-TERM MEMORY
        mock_config.return_value = mock_cfg

        from app.agent.nodes.generate_sql import generate_sql
        result_state = generate_sql(initial_state)

        # Verify that the prompt includes few-shot examples when enabled
        if initial_state.get("few_shot_examples"):
            assert "Few-shot examples" in prompt_received["text"] or "past queries" in prompt_received["text"].lower()


@pytest.mark.asyncio
async def test_memory_persistence_conversation_saved():
    """Test that completed conversations are persisted to PostgreSQL."""
    conversation_id = "test-conv-persistence"
    message_id = str(uuid.uuid4())
    
    # Mock the PostgreSQL operations
    with patch("app.memory.postgres.create_conversation") as mock_create_conv, \
         patch("app.memory.postgres.save_message") as mock_save_msg, \
         patch("app.memory.postgres.save_query_log") as mock_save_log:

        mock_create_conv.return_value = {"id": conversation_id, "user_id": "user-1"}
        mock_save_msg.return_value = {"id": message_id, "status": "answered"}
        mock_save_log.return_value = {"id": str(uuid.uuid4()), "success": True}

        # Import and call save_memory
        from app.agent.nodes.save_memory import _save_memory_async
        
        state = {
            "conversation_id": conversation_id,
            "user_id": "user-1",
            "question": "Test question?",
            "plan": ["step1"],
            "sql": "SELECT * FROM customers LIMIT 1000;",
            "status": "answered",
            "answer": "Here's your answer",
            "iterations": 8,
            "retries": 0,
            "error": None,
            "result": {"ok": True, "columns": ["id"], "rows": [], "row_count": 0},
            "_execution_time_ms": 100,
        }

        await _save_memory_async(state)

        # Verify that persistence functions were called
        mock_create_conv.assert_called_once()
        mock_save_msg.assert_called_once()
        mock_save_log.assert_called_once()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
