"""Observability setup with Langfuse and structured logging."""

import json
import logging
import logging.config
from typing import Any, Optional

from app.config import get_config
from app.middleware import get_request_id, get_user_id

logger = logging.getLogger(__name__)

# Global Langfuse client (lazy-initialized)
_langfuse_client: Optional[Any] = None


class StructuredFormatter(logging.Formatter):
    """Structured JSON formatter for logging."""

    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON."""
        log_data = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Add request context if available
        try:
            request_id = get_request_id()
            if request_id:
                log_data["request_id"] = request_id
            user_id = get_user_id()
            if user_id:
                log_data["user_id"] = user_id
        except LookupError:
            # Context not available (e.g., in non-request thread)
            pass

        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        # Add extra fields if present
        if hasattr(record, "extra_data"):
            log_data.update(record.extra_data)

        return json.dumps(log_data)


def setup_structured_logging() -> None:
    """Configure structured JSON logging."""
    config = get_config()

    logging_config = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "json": {
                "()": StructuredFormatter,
            },
            "standard": {
                "format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
            },
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "json" if not config.debug else "standard",
                "stream": "ext://sys.stdout",
            },
        },
        "root": {
            "level": "INFO" if not config.debug else "DEBUG",
            "handlers": ["console"],
        },
        "loggers": {
            "app": {
                "level": "INFO" if not config.debug else "DEBUG",
            },
            "uvicorn": {
                "level": "INFO",
            },
        },
    }

    logging.config.dictConfig(logging_config)
    logger.info("Structured logging configured")


def get_langfuse_client() -> Optional[Any]:
    """Get or create Langfuse client."""
    global _langfuse_client

    if _langfuse_client is None:
        config = get_config()

        if not config.langfuse_public_key or not config.langfuse_secret_key:
            logger.debug("Langfuse keys not configured; tracing disabled")
            return None

        try:
            from langfuse import Langfuse

            _langfuse_client = Langfuse(
                public_key=config.langfuse_public_key,
                secret_key=config.langfuse_secret_key,
                host=getattr(config, "langfuse_host", None),
            )
            logger.info("Langfuse client initialized")
        except ImportError:
            logger.warning("Langfuse not installed; tracing disabled")
            return None
        except Exception as e:
            logger.error(f"Failed to initialize Langfuse: {e}")
            return None

    return _langfuse_client


def setup_langfuse() -> None:
    """Initialize Langfuse for LLM tracing."""
    client = get_langfuse_client()
    if client:
        logger.info("Langfuse observability enabled")
    else:
        logger.info("Langfuse observability disabled")


def trace_request(
    name: str,
    request_id: str,
    user_id: str,
    metadata: Optional[dict[str, Any]] = None,
) -> Any:
    """Create a Langfuse trace for a request.

    Args:
        name: Name of the trace (e.g., "chat_request")
        request_id: Unique request identifier
        user_id: User making the request
        metadata: Additional metadata to include

    Returns:
        Langfuse trace object or None if Langfuse disabled
    """
    client = get_langfuse_client()
    if not client:
        return None

    try:
        trace = client.trace(
            name=name,
            user_id=user_id,
            session_id=request_id,
            metadata={
                "request_id": request_id,
                "user_id": user_id,
                **(metadata or {}),
            },
        )
        return trace
    except Exception as e:
        logger.error(f"Failed to create Langfuse trace: {e}")
        return None


def trace_span(
    trace: Any,
    name: str,
    span_type: str,
    metadata: Optional[dict[str, Any]] = None,
    input_data: Optional[dict[str, Any]] = None,
    output_data: Optional[dict[str, Any]] = None,
) -> Any:
    """Create a span within a trace.

    Args:
        trace: Parent Langfuse trace
        name: Name of the span
        span_type: Type of span (e.g., "node", "tool", "llm")
        metadata: Additional metadata
        input_data: Input to the span
        output_data: Output from the span

    Returns:
        Langfuse span object or None
    """
    if not trace:
        return None

    try:
        span = trace.span(
            name=name,
            metadata={
                "span_type": span_type,
                **(metadata or {}),
            },
            input=input_data,
            output=output_data,
        )
        return span
    except Exception as e:
        logger.error(f"Failed to create Langfuse span: {e}")
        return None


def trace_llm_call(
    trace: Any,
    model: str,
    prompt: str,
    completion: str,
    tokens_prompt: int,
    tokens_completion: int,
    cost_usd: float,
) -> None:
    """Log an LLM call to Langfuse.

    Args:
        trace: Parent trace
        model: Model name (e.g., "gpt-4-turbo")
        prompt: Prompt text
        completion: Completion text
        tokens_prompt: Prompt tokens
        tokens_completion: Completion tokens
        cost_usd: Cost in USD
    """
    if not trace:
        return

    try:
        trace.generation(
            name="llm_call",
            model=model,
            input=prompt,
            output=completion,
            usage={
                "prompt_tokens": tokens_prompt,
                "completion_tokens": tokens_completion,
                "total_tokens": tokens_prompt + tokens_completion,
            },
            metadata={
                "cost_usd": cost_usd,
            },
        )
    except Exception as e:
        logger.error(f"Failed to log LLM call to Langfuse: {e}")
