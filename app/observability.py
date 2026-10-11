"""Observability setup with Langfuse."""

import logging
from app.config import settings

logger = logging.getLogger(__name__)


def setup_langfuse() -> None:
    """Initialize Langfuse for LLM tracing."""
    if not settings.langfuse_public_key or not settings.langfuse_secret_key:
        logger.warning("Langfuse keys not configured; tracing disabled")
        return

    try:
        from langfuse import Langfuse

        Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
        )
        logger.info("Langfuse initialized")
    except ImportError:
        logger.warning("Langfuse not installed; tracing disabled")
    except Exception as e:
        logger.error(f"Failed to initialize Langfuse: {e}")
