"""Custom exceptions for QueryPilot."""


class QueryPilotException(Exception):
    """Base exception for all QueryPilot errors."""

    pass


class ValidationError(QueryPilotException):
    """Raised when SQL validation fails."""

    pass


class ExecutionError(QueryPilotException):
    """Raised when SQL execution fails."""

    pass


class SchemaError(QueryPilotException):
    """Raised when schema retrieval or processing fails."""

    pass


class TimeoutError(ExecutionError):
    """Raised when query execution times out."""

    pass


class RowLimitExceeded(ExecutionError):
    """Raised when query result exceeds row limit."""

    pass
