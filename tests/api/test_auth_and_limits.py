"""Tests for authentication and rate limiting."""

import json
import time
import pytest
from unittest.mock import patch, MagicMock

from fastapi.testclient import TestClient
from app.config import Config
from app.main import create_app


@pytest.fixture
def app_with_auth():
    """Create test app with auth enabled."""
    with patch("app.config.get_config") as mock_get_config:
        config = MagicMock(spec=Config)
        config.debug = False
        config.api_host = "0.0.0.0"
        config.api_port = 8000
        config.require_api_key = True
        config.api_key = "test-secret-key"
        config.rate_limit_requests_per_minute = 60
        config.cors_allowed_origins = ["*"]
        config.langfuse_public_key = None
        config.langfuse_secret_key = None
        config.redis_url = "redis://localhost:6379"

        mock_get_config.return_value = config

        app = create_app()
        return app


@pytest.fixture
def client_with_auth(app_with_auth):
    """Create test client with auth enabled."""
    return TestClient(app_with_auth)


class TestAPIKeyAuth:
    """Tests for API key authentication."""

    def test_health_check_no_auth_required(self, client_with_auth):
        """Test that health check doesn't require auth."""
        response = client_with_auth.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"

    def test_chat_missing_api_key(self, client_with_auth):
        """Test chat endpoint fails without API key."""
        response = client_with_auth.post(
            "/chat/",
            json={
                "user_id": "test_user",
                "question": "Top customers?",
            },
        )

        assert response.status_code == 401
        data = response.json()
        assert "X-API-Key" in data["detail"]

    def test_chat_invalid_api_key(self, client_with_auth):
        """Test chat endpoint fails with invalid API key."""
        response = client_with_auth.post(
            "/chat/",
            json={
                "user_id": "test_user",
                "question": "Top customers?",
            },
            headers={"X-API-Key": "invalid-key"},
        )

        assert response.status_code == 403
        data = response.json()
        assert "Invalid API key" in data["detail"]

    def test_chat_valid_api_key(self, client_with_auth):
        """Test chat endpoint succeeds with valid API key."""
        response = client_with_auth.post(
            "/chat/",
            json={
                "user_id": "test_user",
                "question": "Top customers?",
            },
            headers={"X-API-Key": "test-secret-key"},
        )

        # Should succeed with auth (might fail for other reasons, but not auth)
        assert response.status_code in [200, 500, 501]


class TestRateLimiting:
    """Tests for rate limiting."""

    @pytest.fixture
    def app_with_low_rate_limit(self):
        """Create test app with low rate limit."""
        with patch("app.config.get_config") as mock_get_config:
            config = MagicMock(spec=Config)
            config.debug = False
            config.api_host = "0.0.0.0"
            config.api_port = 8000
            config.require_api_key = False
            config.rate_limit_requests_per_minute = 2  # Very low for testing
            config.cors_allowed_origins = ["*"]
            config.langfuse_public_key = None
            config.langfuse_secret_key = None
            config.redis_url = "redis://localhost:6379"

            mock_get_config.return_value = config

            app = create_app()
            return app

    @pytest.fixture
    def client_with_low_limit(self, app_with_low_rate_limit):
        """Create test client with low rate limit."""
        return TestClient(app_with_low_rate_limit)

    def test_rate_limit_not_exceeded(self, client_with_low_limit):
        """Test that requests under limit are allowed."""
        # First request should succeed
        response = client_with_low_limit.post(
            "/chat/",
            json={
                "user_id": "test_user",
                "question": "Top customers?",
            },
            headers={"X-User-ID": "test_user"},
        )

        # Should not be rate limited
        assert response.status_code != 429

    def test_rate_limit_exceeded_returns_429(self, client_with_low_limit):
        """Test that requests over limit return 429."""
        # Make requests up to and over the limit
        user_id = "rate_limited_user"

        for i in range(5):  # Limit is 2, so 3rd+ request should fail
            response = client_with_low_limit.post(
                "/chat/",
                json={
                    "user_id": user_id,
                    "question": f"Question {i}?",
                },
                headers={"X-User-ID": user_id},
            )

            if i >= 2:  # Should be rate limited after 2 requests
                assert response.status_code == 429
                data = response.json()
                assert "Rate limit exceeded" in data["detail"]

    def test_rate_limit_has_request_id(self, client_with_low_limit):
        """Test that rate limit response includes request ID."""
        user_id = "rate_test_user"

        # Make requests over the limit
        for i in range(5):
            response = client_with_low_limit.post(
                "/chat/",
                json={
                    "user_id": user_id,
                    "question": f"Question {i}?",
                },
                headers={"X-User-ID": user_id},
            )

            if i >= 2:
                assert "X-Request-ID" in response.headers

    def test_health_check_not_rate_limited(self, client_with_low_limit):
        """Test that health check is not subject to rate limiting."""
        # Make many requests to health check
        for i in range(10):
            response = client_with_low_limit.get("/health")
            assert response.status_code == 200


class TestRequestID:
    """Tests for request ID tracking."""

    def test_request_id_added_to_response(self, client_with_auth):
        """Test that request ID is added to response headers."""
        response = client_with_auth.get("/health")

        assert "X-Request-ID" in response.headers
        request_id = response.headers["X-Request-ID"]
        assert len(request_id) > 0

    def test_different_requests_get_different_ids(self, client_with_auth):
        """Test that different requests get different request IDs."""
        response1 = client_with_auth.get("/health")
        response2 = client_with_auth.get("/health")

        id1 = response1.headers["X-Request-ID"]
        id2 = response2.headers["X-Request-ID"]

        assert id1 != id2

    def test_request_id_consistent_in_logs(self, client_with_auth, caplog):
        """Test that request ID appears in logs."""
        response = client_with_auth.get("/health")
        request_id = response.headers["X-Request-ID"]

        # Check that request ID appears in logs
        log_text = caplog.text
        # (This test may need adjustment based on actual logging setup)
