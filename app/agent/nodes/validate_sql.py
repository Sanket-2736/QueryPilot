"""Validate SQL for safety (deterministic, no LLM)."""

import logging
from typing import Any

import sqlglot
from sqlglot import exp

from app.agent.state import AgentState

logger = logging.getLogger(__name__)

FORBIDDEN = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Drop,
    exp.Create,
    exp.Alter,
    exp.Command,
    exp.TruncateTable,
)

FORBIDDEN_FUNCTIONS = {
    "pg_sleep",
    "pg_read_file",
    "pg_write_file",
    "dblink",
    "set_config",
    "current_setting",
}


def validate_sql(state: AgentState) -> dict[str, Any]:
    """Validate SQL for safety and correctness.

    Args:
        state: Current agent state.

    Returns:
        Updated state with validation result.
    """
    logger.info("Validating SQL")

    if not state.get("sql"):
        state["validation"] = {"ok": False, "reason": "no_sql_generated"}
        state["iterations"] = state["iterations"] + 1
        return state

    try:
        sql = state["sql"]

        # Parse SQL
        try:
            trees = sqlglot.parse(sql, read="postgres")
        except sqlglot.errors.ParseError as e:
            state["validation"] = {
                "ok": False,
                "reason": f"syntax_error: {str(e)}",
                "destructive": False,
            }
            state["iterations"] = state["iterations"] + 1
            return state

        # Only allow single SELECT statement
        if len(trees) != 1:
            state["validation"] = {
                "ok": False,
                "reason": "only_single_statements_allowed",
                "destructive": False,
            }
            state["iterations"] = state["iterations"] + 1
            return state

        tree = trees[0]

        # Ensure it's a SELECT
        if not isinstance(tree, exp.Select) and not tree.find(exp.Select):
            state["validation"] = {
                "ok": False,
                "reason": "only_select_allowed",
                "destructive": False,
            }
            state["iterations"] = state["iterations"] + 1
            return state

        # Check for forbidden operations (write/DDL)
        if tree.find(*FORBIDDEN):
            state["validation"] = {
                "ok": False,
                "reason": "write_or_ddl_operation_detected",
                "destructive": True,
            }
            state["iterations"] = state["iterations"] + 1
            return state

        # Check for forbidden functions
        for func in tree.find_all(exp.Anonymous):
            if func.name.lower() in FORBIDDEN_FUNCTIONS:
                state["validation"] = {
                    "ok": False,
                    "reason": f"forbidden_function_detected: {func.name}",
                    "destructive": True,
                }
                state["iterations"] = state["iterations"] + 1
                return state

        # Extract used tables
        used_tables = {t.name for t in tree.find_all(exp.Table) if t.name}
        cte_names = {c.alias for c in tree.find_all(exp.CTE) if c.alias}

        # Enforce row limit if not already set
        if not tree.args.get("limit"):
            tree = tree.limit(1000)

        normalized_sql = tree.sql(dialect="postgres")

        state["validation"] = {
            "ok": True,
            "reason": None,
            "sql": normalized_sql,
            "tables_used": sorted(used_tables),
            "destructive": False,
        }
        state["iterations"] = state["iterations"] + 1

        return state

    except Exception as e:
        logger.error(f"Validation error: {e}", exc_info=True)
        state["validation"] = {
            "ok": False,
            "reason": f"validation_error: {str(e)}",
            "destructive": False,
        }
        state["iterations"] = state["iterations"] + 1
        return state
