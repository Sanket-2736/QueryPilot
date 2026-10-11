"""Tests for SQL validator."""

import pytest

from app.tools.validator import validate_sql


class TestValidatorBasics:
    """Basic validation tests."""

    def test_valid_select_query(self, allowed_tables: set[str]) -> None:
        """Test that simple SELECT is accepted."""
        sql = "SELECT * FROM customers LIMIT 10;"
        result = validate_sql(sql, allowed_tables)
        assert result["ok"] is True

    def test_rejects_drop_table(self, allowed_tables: set[str]) -> None:
        """Test that DROP TABLE is blocked."""
        sql = "DROP TABLE customers;"
        result = validate_sql(sql, allowed_tables)
        assert result["ok"] is False
        assert "write_or_ddl" in result["reason"]

    def test_rejects_insert(self, allowed_tables: set[str]) -> None:
        """Test that INSERT is blocked."""
        sql = "INSERT INTO customers (name, email) VALUES ('John', 'john@example.com');"
        result = validate_sql(sql, allowed_tables)
        assert result["ok"] is False

    def test_rejects_update(self, allowed_tables: set[str]) -> None:
        """Test that UPDATE is blocked."""
        sql = "UPDATE customers SET name='John' WHERE id=1;"
        result = validate_sql(sql, allowed_tables)
        assert result["ok"] is False

    def test_rejects_delete(self, allowed_tables: set[str]) -> None:
        """Test that DELETE is blocked."""
        sql = "DELETE FROM customers WHERE id=1;"
        result = validate_sql(sql, allowed_tables)
        assert result["ok"] is False

    def test_rejects_unknown_table(self, allowed_tables: set[str]) -> None:
        """Test that queries on unknown tables are blocked."""
        sql = "SELECT * FROM nonexistent_table;"
        result = validate_sql(sql, allowed_tables)
        assert result["ok"] is False
        assert "unknown_tables" in result["reason"]

    def test_enforces_row_limit(self, allowed_tables: set[str]) -> None:
        """Test that row limit is enforced."""
        sql = "SELECT * FROM customers;"
        result = validate_sql(sql, allowed_tables, row_limit=100)
        assert result["ok"] is True
        assert "LIMIT 100" in result["sql"]


class TestValidatorAdvanced:
    """Advanced validation scenarios."""

    def test_join_query(self, allowed_tables: set[str]) -> None:
        """Test that JOIN queries are allowed."""
        sql = "SELECT c.name, o.id FROM customers c JOIN orders o ON c.id = o.customer_id;"
        result = validate_sql(sql, allowed_tables)
        assert result["ok"] is True

    def test_cte_query(self, allowed_tables: set[str]) -> None:
        """Test that CTEs are allowed."""
        sql = "WITH recent_orders AS (SELECT * FROM orders WHERE id > 100) SELECT * FROM recent_orders;"
        result = validate_sql(sql, allowed_tables)
        assert result["ok"] is True

    def test_syntax_error(self, allowed_tables: set[str]) -> None:
        """Test that syntax errors are caught."""
        sql = "SELECT * FORM customers;"  # Missing 'F' in FROM
        result = validate_sql(sql, allowed_tables)
        assert result["ok"] is False
        assert "syntax" in result["reason"].lower()

    def test_multiple_statements(self, allowed_tables: set[str]) -> None:
        """Test that multiple statements are rejected."""
        sql = "SELECT * FROM customers; SELECT * FROM orders;"
        result = validate_sql(sql, allowed_tables)
        assert result["ok"] is False
