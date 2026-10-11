"""FastAPI application entry point."""

import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_config
from app.api import chat, conversations, eval as eval_api
from app.middleware import (
    RequestIDMiddleware,
    StructuredLoggingMiddleware,
    RateLimitMiddleware,
    APIKeyAuthMiddleware,
)
from app.observability import setup_langfuse, setup_structured_logging

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    # Setup logging first
    setup_structured_logging()

    config = get_config()

    app = FastAPI(
        title="QueryPilot",
        description="Stateful text-to-SQL agent for business analytics",
        version="0.1.0",
        debug=config.debug,
    )

    # Setup observability (Langfuse)
    setup_langfuse()

    # Add middleware (order matters: innermost first)
    # Request ID must be first to tag all other middleware
    app.add_middleware(RequestIDMiddleware)

    # Structured logging
    app.add_middleware(StructuredLoggingMiddleware)

    # Rate limiting
    app.add_middleware(RateLimitMiddleware, requests_per_minute=config.rate_limit_requests_per_minute)

    # API key authentication (if enabled)
    app.add_middleware(APIKeyAuthMiddleware, require_auth=config.require_api_key)

    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.cors_allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Include routers
    app.include_router(chat.router, prefix="/chat", tags=["chat"])
    app.include_router(conversations.router, prefix="/conversations", tags=["conversations"])
    app.include_router(eval_api.router, prefix="/eval", tags=["eval"])

    @app.get("/health")
    async def health_check() -> dict[str, str]:
        """Health check endpoint.

        Returns:
            Health status
        """
        return {
            "status": "ok",
            "service": "QueryPilot",
            "version": "0.1.0",
        }

    logger.info("FastAPI application created successfully")

    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn

    config = get_config()
    uvicorn.run(
        app,
        host=config.api_host,
        port=config.api_port,
        log_config=None,  # Use our structured logging
    )
