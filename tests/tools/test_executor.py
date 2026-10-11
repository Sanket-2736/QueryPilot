"""Tests for SQL executor."""

import pytest

from app.tools.exceptions import ExecutionError, TimeoutError


class TestExecutorBasics:
    """Basic executor tests."""

    @pytest.mark.asyncio
    async def test_simple_select(self) -> None:
        """Test execution of simple SELECT query."""
        # TODO: Implement test with test database
        pass

    @pytest.mark.asyncio
    async def test_query_timeout(self) -> None:
        """Test that queries timeout correctly."""
        # TODO: Implement test
        pass

    @pytest.mark.asyncio
    async def test_row_limit_enforced(self) -> None:
        """Test that row limit is enforced."""
        # TODO: Implement test
        pass

    @pytest.mark.asyncio
    async def test_read_only_enforced(self) -> None:
        """Test that read-only mode prevents writes."""
        # TODO: Implement test
        pass
