"""Middleware for auth, rate limiting, request tracking, and structured logging."""

import json
import logging
import time
import uuid
from contextvars import ContextVar
from typing import Any, Callable

from fastapi import Request, HTTPException, status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

import redis
from app.config import get_config

# Context variable to hold request ID for logging
request_id_context: ContextVar[str] = ContextVar("request_id", default="")
user_id_context: ContextVar[str] = ContextVar("user_id", default="")

logger = logging.getLogger(__name__)


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Add unique request ID to all requests and logs."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Generate request ID and attach to context."""
        request_id = str(uuid.uuid4())
        request_id_context.set(request_id)

        # Try to extract user ID from header
        user_id = request.headers.get("X-User-ID", "anonymous")
        user_id_context.set(user_id)

        # Add request ID to request state
        request.state.request_id = request_id
        request.state.user_id = user_id
        request.state.start_time = time.time()

        response = await call_next(request)

        # Add request ID to response headers
        response.headers["X-Request-ID"] = request_id

        return response


class StructuredLoggingMiddleware(BaseHTTPMiddleware):
    """Log all requests with structured JSON format."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Log request and response with structured data."""
        start_time = time.time()
        request_id = request.state.request_id
        user_id = request.state.user_id

        # Log request
        logger.info(
            json.dumps({
                "event": "request_start",
                "request_id": request_id,
                "user_id": user_id,
                "method": request.method,
                "path": request.url.path,
                "timestamp": time.time(),
            })
        )

        response = await call_next(request)

        # Log response
        elapsed_ms = (time.time() - start_time) * 1000
        logger.info(
            json.dumps({
                "event": "request_end",
                "request_id": request_id,
                "user_id": user_id,
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "elapsed_ms": elapsed_ms,
                "timestamp": time.time(),
            })
        )

        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Rate limit per user using Redis."""

    def __init__(self, app, requests_per_minute: int = 60):
        """Initialize rate limiter.

        Args:
            app: FastAPI app
            requests_per_minute: Max requests per minute per user
        """
        super().__init__(app)
        self.requests_per_minute = requests_per_minute
        self.redis_client = None

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Check rate limit before processing request."""
        config = get_config()

        # Skip rate limiting for health checks
        if request.url.path == "/health":
            return await call_next(request)

        # Initialize Redis client if needed
        if self.redis_client is None:
            try:
                self.redis_client = redis.from_url(config.redis_url, decode_responses=True)
            except Exception as e:
                logger.warning(f"Failed to initialize Redis for rate limiting: {e}")
                # Continue without rate limiting
                return await call_next(request)

        user_id = request.state.user_id
        request_id = request.state.request_id

        # Rate limit key: user:{user_id}:requests:{minute}
        minute = int(time.time() // 60)
        rate_limit_key = f"user:{user_id}:requests:{minute}"

        try:
            # Increment counter
            count = self.redis_client.incr(rate_limit_key)

            # Set expiry on first increment
            if count == 1:
                self.redis_client.expire(rate_limit_key, 60)

            # Check limit
            if count > self.requests_per_minute:
                logger.warning(
                    json.dumps({
                        "event": "rate_limit_exceeded",
                        "request_id": request_id,
                        "user_id": user_id,
                        "path": request.url.path,
                        "count": count,
                        "limit": self.requests_per_minute,
                    })
                )

                return Response(
                    content=json.dumps({
                        "detail": "Rate limit exceeded",
                        "limit": self.requests_per_minute,
                        "window": "1 minute",
                    }),
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    media_type="application/json",
                    headers={"X-Request-ID": request_id},
                )

        except Exception as e:
            logger.error(f"Rate limit check failed: {e}")
            # Continue without rate limiting on error

        return await call_next(request)


class APIKeyAuthMiddleware(BaseHTTPMiddleware):
    """Validate API key from X-API-Key header."""

    def __init__(self, app, require_auth: bool = True):
        """Initialize auth middleware.

        Args:
            app: FastAPI app
            require_auth: Whether to require authentication
        """
        super().__init__(app)
        self.require_auth = require_auth

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Check API key before processing request."""
        # Skip auth for health checks
        if request.url.path == "/health":
            return await call_next(request)

        if not self.require_auth:
            return await call_next(request)

        config = get_config()

        # Get API key from header
        api_key = request.headers.get("X-API-Key")

        if not api_key:
            logger.warning(
                json.dumps({
                    "event": "auth_missing",
                    "request_id": request.state.request_id,
                    "path": request.url.path,
                })
            )
            return Response(
                content=json.dumps({"detail": "Missing X-API-Key header"}),
                status_code=status.HTTP_401_UNAUTHORIZED,
                media_type="application/json",
                headers={"X-Request-ID": request.state.request_id},
            )

        # Validate API key (simple check against configured value)
        if hasattr(config, "api_key") and config.api_key and api_key != config.api_key:
            logger.warning(
                json.dumps({
                    "event": "auth_invalid",
                    "request_id": request.state.request_id,
                    "path": request.url.path,
                })
            )
            return Response(
                content=json.dumps({"detail": "Invalid API key"}),
                status_code=status.HTTP_403_FORBIDDEN,
                media_type="application/json",
                headers={"X-Request-ID": request.state.request_id},
            )

        return await call_next(request)


def get_request_id() -> str:
    """Get current request ID from context."""
    return request_id_context.get()


def get_user_id() -> str:
    """Get current user ID from context."""
    return user_id_context.get()
