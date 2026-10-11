"""Shared test fixtures for QueryPilot."""

import pytest


@pytest.fixture
def sample_schema() -> dict:
    """Sample database schema for testing."""
    return {
        "customers": {
            "columns": [
                {"name": "id", "type": "integer", "nullable": False},
                {"name": "name", "type": "character varying", "nullable": False},
                {"name": "email", "type": "character varying", "nullable": False},
            ]
        },
        "orders": {
            "columns": [
                {"name": "id", "type": "integer", "nullable": False},
                {"name": "customer_id", "type": "integer", "nullable": False},
                {"name": "order_date", "type": "date", "nullable": False},
                {"name": "status", "type": "character varying", "nullable": False},
                {"name": "total_amount", "type": "numeric", "nullable": True},
            ]
        },
    }


@pytest.fixture
def allowed_tables() -> set[str]:
    """Set of allowed table names for validation tests."""
    return {"customers", "orders", "products", "order_items", "reviews"}
