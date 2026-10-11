"""Agent state definition for the LangGraph state machine."""

from typing import Any, Literal, Optional, TypedDict


class AgentState(TypedDict):
    """State container for the text-to-SQL agent.

    Carries conversation context, query state, and execution status through all nodes.
    """

    # Conversation context
    conversation_id: str
    user_id: str
    question: str

    # History and context
    history: list[dict[str, Any]]  # Previous Q/SQL/result tuples
    few_shot_examples: list[dict[str, Any]]  # Similar past queries for few-shot learning (long-term memory)
    plan: list[str]  # Ordered steps from planner

    # Schema and query generation
    needs_schema: bool
    schema_context: str  # Relevant tables and columns

    # SQL and validation
    sql: Optional[str]
    validation: Optional[dict[str, Any]]  # {ok, reason?, tables_used?, sql?}

    # Execution results
    result: Optional[dict[str, Any]]  # {columns, rows, row_count} or error dict

    # Error tracking
    error: Optional[str]

    # Execution metrics (for observability)
    _execution_time_ms: Optional[int] = None  # Internal tracking
    _tokens_used: Optional[int] = None  # Internal tracking
    _cost_usd: Optional[float] = None  # Internal tracking

    # Control flow
    retries: int  # Count of fix_sql attempts
    iterations: int  # Count of nodes executed
    status: Literal["running", "answered", "rejected", "failed", "needs_clarification"]

    # Final output
    answer: Optional[str]
