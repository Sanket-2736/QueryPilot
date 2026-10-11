"""Failure mode injection for testing robustness.

These functions simulate various failure modes to test agent mitigation strategies:
- wrong_table: Schema retrieval returns irrelevant tables
- fan_out_join: Schema retrieval allows fan-out join leading to double-counting
- invalid_sql: LLM generates syntactically invalid SQL
- destructive_sql: LLM generates DROP/DELETE/UPDATE/INSERT statements
- ambiguous_question: Question lacks clarity on metrics/time periods
- missing_schema_info: Required tables are not returned by schema retrieval
"""

import copy
from typing import Any


def inject_wrong_table_error(state: dict[str, Any]) -> dict[str, Any]:
    """Simulate wrong table returned during schema retrieval.

    Returns an irrelevant table in schema_context, causing generation failures.
    Agent should handle this by iterating schema retrieval or handling errors.
    """
    state_copy = copy.deepcopy(state)

    # Replace schema_context with an irrelevant table
    state_copy["schema_context"] = """
    Table: pg_catalog.pg_tables
    Columns: schemaname (text), tablename (text), tableowner (name), ...
    
    Table: information_schema.tables
    Columns: table_catalog, table_schema, table_name, table_type, ...
    """
    state_copy["needs_schema"] = True

    return state_copy


def inject_fan_out_join_error(state: dict[str, Any]) -> dict[str, Any]:
    """Simulate missing junction table in schema retrieval.

    Omits order_items table which is needed to avoid fan-out joins.
    Agent must detect and request schema refresh.
    """
    state_copy = copy.deepcopy(state)

    # Return only customers and orders, missing order_items junction table
    state_copy["schema_context"] = """
    Table: customers
    Columns: id (int), name (varchar), email (varchar), segment (varchar)
    Primary Key: id

    Table: orders
    Columns: id (int), customer_id (int), date (date), total (decimal), status (varchar)
    Foreign Key: customer_id -> customers.id
    """
    state_copy["needs_schema"] = True

    return state_copy


def inject_invalid_sql_error(state: dict[str, Any]) -> dict[str, Any]:
    """Simulate LLM generating syntactically invalid SQL.

    Inject a malformed SELECT statement that will fail validation.
    Agent should catch this in validate_sql and iterate.
    """
    state_copy = copy.deepcopy(state)

    # Inject invalid SQL: missing FROM clause
    state_copy["sql"] = "SELECT COUNT(*) WHERE status = 'active';"

    return state_copy


def inject_destructive_sql_error(state: dict[str, Any]) -> dict[str, Any]:
    """Simulate LLM attempting a destructive query.

    Inject a DROP TABLE, DELETE, UPDATE, or INSERT statement.
    Agent should reject this at validate_sql with 100% block rate.
    """
    state_copy = copy.deepcopy(state)

    # Inject a destructive statement
    if state.get("question", "").lower().find("drop") != -1:
        state_copy["sql"] = "DROP TABLE customers;"
    else:
        state_copy["sql"] = "DELETE FROM orders WHERE id > 0;"

    return state_copy


def inject_ambiguous_question_error(state: dict[str, Any]) -> dict[str, Any]:
    """Simulate an ambiguous natural language question.

    Inject a question that lacks specificity (e.g., "Top products" without
    metric, "Revenue" without time period). Agent should respond with clarification.
    """
    state_copy = copy.deepcopy(state)

    # Replace with ambiguous question
    state_copy["question"] = "What are the top products?"

    return state_copy


def inject_missing_schema_error(state: dict[str, Any]) -> dict[str, Any]:
    """Simulate missing required tables in schema retrieval.

    For a question about order items, omit the order_items table.
    Agent should fail and require clarification or schema adjustment.
    """
    state_copy = copy.deepcopy(state)

    # Return partial schema missing key tables
    state_copy["schema_context"] = """
    Table: customers
    Columns: id (int), name (varchar), email (varchar)
    Primary Key: id

    Table: orders
    Columns: id (int), customer_id (int), date (date), total (decimal)
    Foreign Key: customer_id -> customers.id
    """
    # Note: order_items table is missing, causing query generation to fail
    state_copy["needs_schema"] = True

    return state_copy


# Mapping of failure modes to injection functions
FAILURE_MODES = {
    "wrong_table": inject_wrong_table_error,
    "fan_out_join": inject_fan_out_join_error,
    "invalid_sql": inject_invalid_sql_error,
    "destructive_sql": inject_destructive_sql_error,
    "ambiguous_question": inject_ambiguous_question_error,
    "missing_schema": inject_missing_schema_error,
}
