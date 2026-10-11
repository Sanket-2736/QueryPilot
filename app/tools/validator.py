"""Deterministic SQL validator using sqlglot AST parsing.

Ensures all queries are SELECT-only and use allowed tables.
This is a critical safety component—validation is never delegated to the LLM.
"""

import sqlglot
from sqlglot import exp

from app.tools.exceptions import ValidationError

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


def validate_sql(sql: str, allowed_tables: set[str], row_limit: int = 1000) -> dict:
    """Validate SQL query for safety and correctness.

    Args:
        sql: SQL query string.
        allowed_tables: Set of table names allowed in the query.
        row_limit: Maximum number of rows to return.

    Returns:
        Dict with keys: ok (bool), reason (str), sql (str), tables_used (set).

    Raises:
        ValidationError: If validation fails critically.
    """
    # Parse SQL
    try:
        trees = sqlglot.parse(sql, read="postgres")
    except sqlglot.errors.ParseError as e:
        return {"ok": False, "reason": f"syntax_error: {str(e)}"}

    # Only allow single SELECT statement
    if len(trees) != 1:
        return {"ok": False, "reason": "only_single_statements_allowed"}

    tree = trees[0]

    # Ensure it's a SELECT
    if not isinstance(tree, exp.Select) and not tree.find(exp.Select):
        return {"ok": False, "reason": "only_select_allowed"}

    # Check for forbidden operations
    if tree.find(*FORBIDDEN):
        return {"ok": False, "reason": "write_or_ddl_operation_detected"}

    # Extract used tables
    used_tables = {t.name for t in tree.find_all(exp.Table)}
    cte_names = {c.alias for c in tree.find_all(exp.CTE)}
    unknown_tables = (used_tables - allowed_tables) - cte_names

    if unknown_tables:
        return {
            "ok": False,
            "reason": f"unknown_tables: {', '.join(sorted(unknown_tables))}",
        }

    # Enforce row limit if not already set
    if not tree.args.get("limit"):
        tree = tree.limit(row_limit)

    return {
        "ok": True,
        "reason": None,
        "sql": tree.sql(dialect="postgres"),
        "tables_used": sorted(used_tables),
    }
