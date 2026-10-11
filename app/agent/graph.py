"""LangGraph state machine for the text-to-SQL agent."""

import logging
from typing import Any, Literal

from langgraph.graph import StateGraph, END

from app.agent.nodes import (
    analyze_result,
    execute_sql,
    final_answer,
    fix_sql,
    generate_sql,
    load_memory,
    planner,
    retrieve_schema,
    save_memory,
    validate_sql,
)
from app.agent.state import AgentState

logger = logging.getLogger(__name__)

# Constants
MAX_RETRIES = 3
MAX_ITERATIONS = 10


def after_planner(state: AgentState) -> Literal["final_answer", "retrieve_schema", "generate_sql"]:
    """Route after planner."""
    # Check iteration budget
    if state["iterations"] >= MAX_ITERATIONS:
        state["status"] = "failed"
        state["error"] = f"Iteration budget exhausted ({MAX_ITERATIONS} iterations)"
        return "final_answer"

    # If planner failed, go to final_answer
    if state["status"] != "running" and state["status"] != "needs_clarification":
        return "final_answer"

    # If ambiguous, go to final answer
    if state["status"] == "needs_clarification":
        return "final_answer"

    # If schema is needed, retrieve it
    if state["needs_schema"]:
        return "retrieve_schema"

    # Otherwise, jump to SQL generation
    return "generate_sql"


def after_retrieve_schema(state: AgentState) -> Literal["final_answer", "generate_sql"]:
    """Route after retrieve_schema."""
    if state["iterations"] >= MAX_ITERATIONS:
        return "final_answer"
    return "generate_sql"


def after_validate_sql(state: AgentState) -> Literal["execute_sql", "fix_sql", "final_answer"]:
    """Route after validate_sql."""
    if state["iterations"] >= MAX_ITERATIONS:
        return "final_answer"

    validation = state.get("validation", {})

    # If validation passed, execute
    if validation.get("ok"):
        return "execute_sql"

    # If destructive, reject immediately (set status in final_answer)
    if validation.get("destructive"):
        state["status"] = "rejected"
        state["answer"] = "Your query would require a write operation, which is not allowed. Only SELECT queries are supported."
        return "final_answer"

    # If retries exhausted, fail
    if state["retries"] >= MAX_RETRIES:
        state["status"] = "failed"
        state["error"] = f"SQL validation failed after {MAX_RETRIES} retry attempts: {validation.get('reason')}"
        return "final_answer"

    # Otherwise, try to fix
    return "fix_sql"


def after_execute_sql(state: AgentState) -> Literal["analyze_result", "fix_sql", "planner", "final_answer"]:
    """Route after execute_sql."""
    if state["iterations"] >= MAX_ITERATIONS:
        state["status"] = "failed"
        state["error"] = f"Iteration budget exhausted ({MAX_ITERATIONS} iterations)"
        return "final_answer"

    result = state.get("result", {})

    # If execution succeeded, analyze
    if result.get("ok"):
        return "analyze_result"

    # If execution failed
    # Try fix_sql first, then replan
    if state["retries"] < MAX_RETRIES:
        if state["retries"] < 2:
            # First/second failure: try to fix the SQL
            return "fix_sql"
        else:
            # Third attempt (retries=2, about to hit 3): replan with fresh schema
            return "planner"

    # Retries exhausted
    state["status"] = "failed"
    state["error"] = f"Query execution failed after {MAX_RETRIES} retry attempts: {result.get('error')}"
    return "final_answer"


def after_fix_sql(state: AgentState) -> Literal["validate_sql"]:
    """Route after fix_sql."""
    # Always re-validate after fixing
    return "validate_sql"


def build_graph() -> StateGraph:
    """Build and return the LangGraph state machine."""
    graph = StateGraph(AgentState)

    # Add all nodes
    graph.add_node("load_memory", load_memory)
    graph.add_node("planner", planner)
    graph.add_node("retrieve_schema", retrieve_schema)
    graph.add_node("generate_sql", generate_sql)
    graph.add_node("validate_sql", validate_sql)
    graph.add_node("execute_sql", execute_sql)
    graph.add_node("fix_sql", fix_sql)
    graph.add_node("analyze_result", analyze_result)
    graph.add_node("final_answer", final_answer)
    graph.add_node("save_memory", save_memory)

    # Set entry point
    graph.set_entry_point("load_memory")

    # Add edges
    graph.add_edge("load_memory", "planner")
    graph.add_conditional_edges("planner", after_planner)
    graph.add_conditional_edges("retrieve_schema", after_retrieve_schema)
    graph.add_edge("generate_sql", "validate_sql")
    graph.add_conditional_edges("validate_sql", after_validate_sql)
    graph.add_conditional_edges("execute_sql", after_execute_sql)
    graph.add_edge("fix_sql", "validate_sql")
    graph.add_edge("analyze_result", "final_answer")
    graph.add_edge("final_answer", "save_memory")
    graph.add_edge("save_memory", END)

    return graph


def compile_graph() -> Any:
    """Compile and return the runnable graph."""
    graph = build_graph()
    return graph.compile()
