"""Tests for chat endpoints."""

import json
import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def app():
    """Create test app instance."""
    return create_app()


@pytest.fixture
def client(app):
    """Create test client."""
    return TestClient(app)


class TestChatStream:
    """Tests for streaming chat endpoint."""

    def test_chat_stream_success(self, client):
        """Test successful chat stream request."""
        response = client.post(
            "/chat/stream",
            json={
                "user_id": "test_user",
                "question": "What are the top 5 customers?",
            },
        )

        assert response.status_code == 200
        assert response.headers["content-type"] == "text/event-stream"

        # Parse SSE events
        events = []
        for line in response.iter_lines():
            if line.startswith("data: "):
                event_data = json.loads(line[6:])
                events.append(event_data)

        # Should have at least start and end events
        assert len(events) > 0

        # Should have final answer event
        final_events = [e for e in events if e["event_type"] == "final_answer"]
        assert len(final_events) > 0

    def test_chat_stream_with_conversation_id(self, client):
        """Test chat stream with provided conversation ID."""
        response = client.post(
            "/chat/stream",
            json={
                "conversation_id": "conv_123",
                "user_id": "test_user",
                "question": "Top customers?",
            },
        )

        assert response.status_code == 200

    def test_chat_stream_has_request_id_header(self, client):
        """Test that response includes request ID header."""
        response = client.post(
            "/chat/stream",
            json={
                "user_id": "test_user",
                "question": "Top 5 customers?",
            },
        )

        assert "X-Request-ID" in response.headers
        request_id = response.headers["X-Request-ID"]
        assert len(request_id) > 0


class TestChatNonStreaming:
    """Tests for non-streaming chat endpoint."""

    def test_chat_success(self, client):
        """Test successful chat request."""
        response = client.post(
            "/chat/",
            json={
                "user_id": "test_user",
                "question": "What are the top 5 customers by revenue?",
            },
        )

        assert response.status_code == 200
        data = response.json()

        # Check response structure
        assert "conversation_id" in data
        assert "message_id" in data
        assert "question" in data
        assert "answer" in data
        assert "status" in data
        assert "iterations" in data
        assert "retries" in data

    def test_chat_with_conversation_id(self, client):
        """Test chat with provided conversation ID."""
        response = client.post(
            "/chat/",
            json={
                "conversation_id": "conv_123",
                "user_id": "test_user",
                "question": "Top customers?",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["conversation_id"] == "conv_123"

    def test_chat_generates_conversation_id(self, client):
        """Test that conversation ID is generated if not provided."""
        response = client.post(
            "/chat/",
            json={
                "user_id": "test_user",
                "question": "Top customers?",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["conversation_id"]

    def test_chat_missing_user_id(self, client):
        """Test chat fails without user ID."""
        response = client.post(
            "/chat/",
            json={
                "question": "Top customers?",
            },
        )

        assert response.status_code == 422  # Validation error

    def test_chat_missing_question(self, client):
        """Test chat fails without question."""
        response = client.post(
            "/chat/",
            json={
                "user_id": "test_user",
            },
        )

        assert response.status_code == 422  # Validation error

    def test_chat_response_has_request_id(self, client):
        """Test that response includes request ID header."""
        response = client.post(
            "/chat/",
            json={
                "user_id": "test_user",
                "question": "Top customers?",
            },
        )

        assert "X-Request-ID" in response.headers
        request_id = response.headers["X-Request-ID"]
        assert len(request_id) > 0
