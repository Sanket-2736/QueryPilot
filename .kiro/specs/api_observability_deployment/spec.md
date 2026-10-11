# Spec: API Service, Observability, and Deployment

**Status**: Starting  
**Reference**: docs/PROJECT_PLAN.md sections 3 (Architecture) and 5 (Project Structure)

## Overview

Build a production-ready FastAPI service with comprehensive observability, authentication, rate limiting, and a single-command Docker deployment. The API streams agent progress as server-sent events (SSE), provides conversation history endpoints, and exposes an evaluation harness. All requests are traced in Langfuse with node-level spans, token counts, and cost metadata.

## Requirements

### 1. FastAPI Endpoints

#### POST /chat – Text-to-SQL Query with SSE Streaming

**Purpose**: Accept a natural language question and stream node-by-node progress events, then the final answer.

**Request**:
```json
{
  "conversation_id": "conv_abc123",
  "user_id": "user_456",
  "question": "Top 5 customers by revenue?"
}
```

**Response** (Server-Sent Events):
```
data: {"type": "node", "node": "load_memory", "status": "running", "timestamp": "2024-10-11T15:30:00Z"}
data: {"type": "node", "node": "planner", "status": "running"}
data: {"type": "llm_call", "tokens": 150, "cost": 0.00075}
data: {"type": "node", "node": "planner", "status": "completed", "plan": ["Get top customers", "Order by revenue"]}
data: {"type": "node", "node": "retrieve_schema", "status": "running"}
data: {"type": "node", "node": "retrieve_schema", "status": "completed", "tables": ["customers", "orders"]}
data: {"type": "node", "node": "generate_sql", "status": "running"}
data: {"type": "llm_call", "tokens": 280, "cost": 0.0014}
data: {"type": "node", "node": "generate_sql", "status": "completed", "sql": "SELECT c.id, c.name, SUM(o.total) FROM customers c JOIN orders o ON c.id = o.customer_id GROUP BY c.id, c.name ORDER BY SUM DESC LIMIT 5;"}
data: {"type": "node", "node": "validate_sql", "status": "running"}
data: {"type": "node", "node": "validate_sql", "status": "completed", "validation": {"ok": true, "tables_used": ["customers", "orders"]}}
data: {"type": "node", "node": "execute_sql", "status": "running"}
data: {"type": "execution", "latency_ms": 125, "row_count": 5}
data: {"type": "node", "node": "analyze_result", "status": "running"}
data: {"type": "node", "node": "analyze_result", "status": "completed"}
data: {"type": "final_answer", "status": "answered", "answer": "The top 5 customers are...", "sql": "SELECT ...", "result": {"columns": ["id", "name", "revenue"], "rows": [...]}, "iterations": 5, "retries": 0, "total_tokens": 430, "total_cost": 0.00215}
```

**Key Features**:
- Streams each node's entry and exit with status
- LLM call events include token count and estimated cost
- Execution events include latency and result statistics
- Final answer includes full context (SQL, result, metrics)
- Client can cancel by closing connection; backend cleans up

**Error Handling**:
```
data: {"type": "error", "message": "Query rejected: destructive SQL detected", "status": "rejected"}
```

**Authentication**: Required (see section 2 below)

**Rate Limit**: 100 requests/minute per user (see section 2 below)

---

#### GET /conversations/{id} – Retrieve Conversation History

**Purpose**: Fetch metadata and message history for a conversation.

**Response**:
```json
{
  "conversation_id": "conv_abc123",
  "user_id": "user_456",
  "created_at": "2024-10-11T14:00:00Z",
  "messages": [
    {
      "turn_number": 1,
      "question": "Top 5 customers by revenue?",
      "status": "answered",
      "sql": "SELECT ...",
      "answer": "The top 5 customers are...",
      "iterations": 5,
      "retries": 0,
      "created_at": "2024-10-11T14:01:00Z"
    },
    {
      "turn_number": 2,
      "question": "Now only for Q4 2024",
      "status": "answered",
      "sql": "SELECT ...",
      "answer": "...",
      "iterations": 4,
      "retries": 1,
      "created_at": "2024-10-11T14:02:30Z"
    }
  ]
}
```

**Authentication**: Required; user must own the conversation

**Rate Limit**: 1000 requests/minute per user

---

#### POST /eval/run – Run Evaluation

**Purpose**: Execute the evaluation harness over the dataset with specified configuration.

**Request**:
```json
{
  "system": "agent",
  "semantic_layer": true,
  "retries_enabled": true,
  "memory_enabled": true,
  "failures": "off"
}
```

**Response**:
```json
{
  "run_id": "eval_xyz789",
  "config": {...},
  "total_queries": 60,
  "succeeded": 57,
  "failed": 3,
  "metrics": {
    "execution_accuracy": 0.95,
    "answer_accuracy": 0.917,
    "schema_retrieval_recall": 0.885,
    "retry_success_rate": 0.80,
    "avg_iterations": 5.2,
    "p50_latency_ms": 1240,
    "p95_latency_ms": 3100,
    "avg_tokens_per_query": 285,
    "total_tokens": 17100,
    "avg_cost_cents": 0.0142,
    "total_cost_cents": 0.85,
    "unsafe_query_block_rate": 1.0
  },
  "created_at": "2024-10-11T15:35:00Z"
}
```

**Authentication**: Admin only (or optional)

**Rate Limit**: 5 requests/hour (expensive operation)

---

#### GET /health – Health Check

**Purpose**: Kubernetes liveness and readiness probe.

**Response**:
```json
{
  "status": "ok",
  "timestamp": "2024-10-11T15:30:00Z",
  "services": {
    "database": "ok",
    "redis": "ok",
    "langfuse": "ok"
  }
}
```

**No Authentication Required**

---

### 2. Authentication and Rate Limiting

#### API Key Authentication

**Mechanism**: Bearer token in `Authorization` header

```
Authorization: Bearer sk_live_1a2b3c4d5e6f7g8h
```

**Implementation**:
- API keys stored as hashed values in App DB
- Lookup by key prefix (e.g., `sk_live_*`)
- Return user_id and org_id from metadata
- Middleware validates on every request (except `/health`)

**API Key Table**:
```sql
CREATE TABLE api_keys (
  id VARCHAR(36) PRIMARY KEY,
  user_id VARCHAR(255) NOT NULL,
  key_prefix VARCHAR(10),      -- First 10 chars of key hash
  key_hash VARCHAR(255) NOT NULL,  -- SHA256 hash
  name VARCHAR(255),            -- "My API Key", "Production", etc.
  active BOOLEAN DEFAULT TRUE,
  created_at TIMESTAMP DEFAULT NOW(),
  last_used_at TIMESTAMP,
  expires_at TIMESTAMP,
  INDEX (user_id, active),
  INDEX (key_prefix)
);
```

---

#### Rate Limiting (Redis-backed)

**Strategy**: Token bucket algorithm with Redis

**Limits**:
- `/chat`: 100 requests/minute per user
- `/conversations/*`: 1000 requests/minute per user
- `/eval/run`: 5 requests/hour per user
- `/health`: unlimited

**Implementation**:
```python
from redis import Redis
from typing import Tuple

async def check_rate_limit(user_id: str, endpoint: str, redis: Redis) -> Tuple[bool, dict]:
    """Check if user has exceeded rate limit for endpoint."""
    key = f"rate_limit:{user_id}:{endpoint}"
    limit, window = get_limit_for_endpoint(endpoint)  # (100, 60) means 100 per 60s
    
    current = await redis.incr(key)
    if current == 1:
        await redis.expire(key, window)
    
    remaining = max(0, limit - current)
    reset_at = await redis.ttl(key)
    
    return (current <= limit, {
        "limit": limit,
        "remaining": remaining,
        "reset_in_seconds": reset_at
    })
```

**Response Headers**:
```
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 67
X-RateLimit-Reset: 1728666660
```

**Rate Limit Exceeded** (HTTP 429):
```json
{
  "error": "rate_limit_exceeded",
  "limit": 100,
  "reset_in_seconds": 45
}
```

---

#### Request IDs

**Mechanism**: Unique identifier attached to every request for tracing

**Generation**:
- Header `X-Request-ID`: use if provided
- Otherwise: generate `req_<uuid4>` in middleware

**Logging**: Include `request_id` in every log line

```python
import logging
import contextvars

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar('request_id', default='')

class RequestIDFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True

# Usage
logger = logging.getLogger(__name__)
logger.addFilter(RequestIDFilter())
logger.info("Processing question", extra={"request_id": request_id})
```

**Propagation**:
- Middleware sets `request_id_var`
- LangGraph nodes read it and pass to Langfuse
- Response header: `X-Request-ID: req_abc123`

---

### 3. Observability: Langfuse Tracing

#### Trace Structure

**One trace per request** with nested spans:

```
Trace: chat_request (request_id=req_abc123)
├─ Span: agent_execution (user_id=user_456, conversation_id=conv_abc)
│  ├─ Span: load_memory
│  ├─ Span: planner (llm_model=gpt-4-turbo)
│  │  └─ Span: planner_llm_call (tokens_in=150, tokens_out=85, cost=0.00075)
│  ├─ Span: retrieve_schema
│  ├─ Span: generate_sql (llm_model=gpt-4-turbo)
│  │  └─ Span: generate_sql_llm_call (tokens_in=280, tokens_out=150, cost=0.0014)
│  ├─ Span: validate_sql (validation_ok=true, tables_used=["customers", "orders"])
│  ├─ Span: execute_sql (latency_ms=125, row_count=5)
│  ├─ Span: analyze_result
│  ├─ Span: final_answer (status=answered)
│  └─ Span: save_memory
└─ Metadata:
   - input: {"question": "..."}
   - output: {"answer": "...", "sql": "..."}
   - user_id: user_456
   - conversation_id: conv_abc
   - model_cost: 0.00215
   - total_iterations: 5
   - total_retries: 0
```

#### Span Tags and Metadata

**Every Span**:
- `node_name`: Name of the node (planner, generate_sql, etc.)
- `status`: running, completed, failed
- `timestamp`: ISO 8601 timestamp
- `duration_ms`: Execution time

**LLM Call Spans**:
- `model`: LLM model name (gpt-4-turbo, claude-3-opus)
- `prompt_tokens`: Input tokens
- `completion_tokens`: Output tokens
- `total_tokens`: Sum
- `cost_usd`: Estimated cost
- `temperature`: Temperature setting
- `max_tokens`: Max tokens setting

**Tool Call Spans** (validator, executor, schema):
- `tool_name`: validator, executor, get_schema
- `input_summary`: Truncated input (for privacy)
- `output_summary`: Result status/metrics
- `error`: Error message if failed

**Execution Span** (execute_sql):
- `sql`: Full query (sanitized if contains PII)
- `latency_ms`: Query time
- `row_count`: Number of rows returned
- `status`: success, timeout, error

#### Implementation

```python
from langfuse import Langfuse
import contextvars

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar('request_id')

class LangfuseTracer:
    """Wrapper for Langfuse tracing."""
    
    def __init__(self, client: Langfuse):
        self.client = client
        self.trace = None
    
    def start_trace(self, request_id: str, user_id: str, conversation_id: str, question: str):
        """Start a new trace for this request."""
        self.trace = self.client.trace(
            name="chat_request",
            user_id=user_id,
            metadata={
                "request_id": request_id,
                "conversation_id": conversation_id,
                "question": question[:200],
            }
        )
    
    def start_node_span(self, node_name: str):
        """Start a span for a node."""
        return self.trace.span(
            name=f"node_{node_name}",
            input={"node": node_name},
        )
    
    def start_llm_span(self, model: str):
        """Start a span for an LLM call."""
        return self.trace.span(
            name="llm_call",
            metadata={"model": model},
        )

# Usage in agent node
async def planner(state: AgentState) -> AgentState:
    request_id = request_id_var.get()
    tracer = state.get("_tracer")  # Passed through state
    
    with tracer.start_node_span("planner") as span:
        with tracer.start_llm_span(config.llm_model) as llm_span:
            result = await llm.invoke(prompt)
            llm_span.end(
                output={"tokens": result.usage.total_tokens, "cost": ...},
                metadata={"tokens_in": result.usage.prompt_tokens, ...}
            )
        span.end(output={"plan": state["plan"]})
    
    return state
```

---

### 4. Structured JSON Logging

**Format**: JSON lines with context

```json
{"timestamp": "2024-10-11T15:30:00.123Z", "level": "INFO", "logger": "app.api.chat", "message": "Chat request received", "request_id": "req_abc123", "user_id": "user_456", "conversation_id": "conv_abc", "question_length": 28}
{"timestamp": "2024-10-11T15:30:01.245Z", "level": "INFO", "logger": "app.agent.nodes.planner", "message": "Planner executed", "request_id": "req_abc123", "node": "planner", "plan_length": 3, "needs_schema": true}
{"timestamp": "2024-10-11T15:30:02.456Z", "level": "INFO", "logger": "app.agent.nodes.generate_sql", "message": "SQL generated", "request_id": "req_abc123", "node": "generate_sql", "sql_length": 145, "tables": ["customers", "orders"]}
{"timestamp": "2024-10-11T15:30:03.789Z", "level": "INFO", "logger": "app.agent.nodes.execute_sql", "message": "Query executed", "request_id": "req_abc123", "node": "execute_sql", "latency_ms": 125, "row_count": 5}
```

**Configuration** (`app/config.py`):

```python
import logging.config
import json

LOGGING_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "json": {
            "()": "pythonjsonlogger.jsonlogger.JsonFormatter",
            "format": "%(timestamp)s %(level)s %(logger)s %(message)s %(request_id)s",
        }
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "json",
            "stream": "ext://sys.stdout",
        }
    },
    "root": {
        "level": "INFO",
        "handlers": ["console"],
    },
}

logging.config.dictConfig(LOGGING_CONFIG)
```

**Context Propagation**:

```python
import contextvars

request_id_var = contextvars.ContextVar('request_id', default='unknown')
user_id_var = contextvars.ContextVar('user_id', default='unknown')
conversation_id_var = contextvars.ContextVar('conversation_id', default='unknown')

@app.middleware("http")
async def add_request_context(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID", f"req_{uuid.uuid4()}")
    token = request_id_var.set(request_id)
    try:
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response
    finally:
        request_id_var.reset(token)
```

---

### 5. Dockerfile and Docker Compose

#### Dockerfile

**Multi-stage build** for efficiency:

```dockerfile
# Stage 1: Build
FROM python:3.11-slim as builder

WORKDIR /app

# Install dependencies
RUN pip install --upgrade pip uv
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen

# Stage 2: Runtime
FROM python:3.11-slim

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"

# Copy application code
COPY app/ app/
COPY alembic/ alembic/
COPY alembic.ini .
COPY seed/ seed/

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run app
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

#### Docker Compose Enhancements

**Integration with seed script**:

```dockerfile
services:
  # ... existing services ...
  
  api:
    build: .
    # ... existing config ...
    depends_on:
      app_db:
        condition: service_healthy
      target_db:
        condition: service_healthy
      redis:
        condition: service_healthy
    command: >
      sh -c "
        alembic upgrade head &&
        python -m seed.generator --customers 100 --orders 500 &&
        python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
      "
```

**Single Command**: `docker-compose up`
- Starts all services (app_db, target_db, redis, langfuse, api)
- Runs migrations automatically
- Seeds sample data
- Waits for health checks
- API is ready at `http://localhost:8000`

---

### 6. Testing

#### Test Suite

**File**: `tests/api/test_api.py`

**Test Cases**:

1. **Authentication**
   - Valid API key
   - Invalid API key (401 Unauthorized)
   - Missing API key (401 Unauthorized)
   - Expired API key (401 Unauthorized)

2. **Rate Limiting**
   - Under limit (200 OK)
   - At limit (200 OK)
   - Over limit (429 Too Many Requests)
   - Rate limit headers present
   - Rate limit resets correctly

3. **Chat Endpoint with SSE**
   - Successful chat returns SSE stream
   - Verify node events appear in order
   - Verify final_answer event present
   - Verify LLM call events with token counts
   - Verify execution events with latency
   - Verify error handling (e.g., destructive SQL rejected)
   - Client disconnect handled gracefully

4. **Conversation History**
   - Retrieve conversation (200 OK)
   - Conversation not found (404)
   - Unauthorized access to other user's conversation (403)
   - Message order correct
   - Pagination works (if implemented)

5. **Evaluation Endpoint**
   - Run evaluation (200 OK)
   - Invalid config (400 Bad Request)
   - Run ID returned
   - Results persisted to database

6. **Health Endpoint**
   - Returns 200 OK
   - Status includes all services
   - Database healthy, Redis healthy, Langfuse healthy

#### Test Implementation Example

```python
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.memory.postgres import save_api_key

@pytest.fixture
def client():
    return TestClient(app)

@pytest.fixture
def valid_api_key(app_db_connection):
    """Create a test API key."""
    key = "sk_test_abc123xyz789"
    save_api_key(
        user_id="test_user",
        key=key,
        name="Test Key"
    )
    return key

def test_chat_requires_auth(client):
    """Chat endpoint requires API key."""
    response = client.post(
        "/chat",
        json={"conversation_id": "conv_1", "user_id": "user_1", "question": "Test?"}
    )
    assert response.status_code == 401
    assert "authentication" in response.json()["error"].lower()

def test_chat_with_valid_key(client, valid_api_key):
    """Chat with valid API key works."""
    response = client.post(
        "/chat",
        json={"conversation_id": "conv_1", "user_id": "user_1", "question": "Test?"},
        headers={"Authorization": f"Bearer {valid_api_key}"}
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "text/event-stream"

def test_chat_sse_events(client, valid_api_key):
    """Chat SSE stream contains expected events."""
    response = client.post(
        "/chat",
        json={"conversation_id": "conv_1", "user_id": "user_1", "question": "How many customers?"},
        headers={"Authorization": f"Bearer {valid_api_key}"}
    )
    
    events = []
    for line in response.iter_lines():
        if line.startswith("data: "):
            event = json.loads(line[6:])
            events.append(event)
    
    # Verify event types
    event_types = {e["type"] for e in events}
    assert "node" in event_types
    assert "final_answer" in event_types
    
    # Verify final answer is last
    assert events[-1]["type"] == "final_answer"
    assert events[-1]["status"] == "answered"

def test_rate_limit_exceeded(client, valid_api_key, redis):
    """Rate limit returns 429 after limit exceeded."""
    # Make 100 requests (at limit)
    for i in range(100):
        response = client.get(
            "/health",
            headers={"Authorization": f"Bearer {valid_api_key}"}
        )
        assert response.status_code == 200
    
    # 101st request should be rate limited
    response = client.get(
        "/health",
        headers={"Authorization": f"Bearer {valid_api_key}"}
    )
    assert response.status_code == 429
    assert "rate_limit_exceeded" in response.json()["error"]

def test_rate_limit_headers(client, valid_api_key):
    """Rate limit headers present in response."""
    response = client.get(
        "/health",
        headers={"Authorization": f"Bearer {valid_api_key}"}
    )
    assert "X-RateLimit-Limit" in response.headers
    assert "X-RateLimit-Remaining" in response.headers
    assert "X-RateLimit-Reset" in response.headers
```

---

## Tasks

### Task 1: API Middleware and Authentication
- [ ] Implement API key authentication middleware
- [ ] Add rate limiting middleware (Redis-backed token bucket)
- [ ] Add request ID context var propagation
- [ ] Update `/chat` endpoint to stream SSE events
- [ ] Update `/conversations` endpoint to require auth
- [ ] Update `/eval/run` endpoint
- [ ] Update `/health` to check services
- [ ] Tests: auth, rate limits, SSE stream

### Task 2: Observability and Logging
- [ ] Set up structured JSON logging
- [ ] Implement Langfuse tracer wrapper
- [ ] Integrate tracer into each agent node
- [ ] Add token count and cost tracking
- [ ] Add request ID to all log lines
- [ ] Tests: verify trace structure, span metadata

### Task 3: Docker Deployment
- [ ] Create optimized Dockerfile (multi-stage)
- [ ] Update docker-compose.yml with auto-seed script
- [ ] Ensure `docker-compose up` brings everything up
- [ ] Test single-command startup
- [ ] Verify all health checks pass
- [ ] Tests: container startup, health checks

### Task 4: API Integration Tests
- [ ] Add FastAPI TestClient tests
- [ ] Test auth failures
- [ ] Test rate limit exceeded
- [ ] Test SSE stream format
- [ ] Test conversation history retrieval
- [ ] Test eval endpoint
- [ ] Ensure 100% of test cases pass

---

## Dependencies

- `fastapi>=0.104.1` – API framework
- `redis>=4.5.0` – Rate limiting and caching
- `langfuse>=2.0.0` – Observability tracing
- `python-json-logger>=2.0.0` – JSON logging
- `psycopg[binary]>=3.1.0` – PostgreSQL async
- `uvicorn>=0.24.0` – ASGI server
- `pytest-asyncio>=0.21.0` – Async test support

---

## Acceptance Criteria

1. ✅ FastAPI service has all 4 endpoints (chat, conversations, eval, health)
2. ✅ POST /chat returns Server-Sent Events stream with node-by-node progress
3. ✅ All endpoints require API key (except /health)
4. ✅ Rate limiting works; X-RateLimit-* headers present
5. ✅ Every request has a request_id, attached to logs and traces
6. ✅ Langfuse traces show node-level spans with token counts and cost
7. ✅ Structured JSON logging; all logs include request_id, user_id
8. ✅ Docker Compose brings up full stack with `docker-compose up`
9. ✅ `docker-compose up` includes auto-seeding and migrations
10. ✅ Health check returns service status (database, redis, langfuse)
11. ✅ All API tests pass (auth, rate limits, SSE, conversation history, eval)
12. ✅ No secrets in logs or traces (sanitized)

---

## Notes

- **SSE streaming**: Use `StreamingResponse` with `async def` endpoint that yields events.
- **Token counting**: Call LLM with `response_format` to get usage; track in span metadata.
- **Cost calculation**: Use published pricing for model (GPT-4: $0.03 per 1K input, $0.06 per 1K output).
- **Health checks**: Lazy-check services; cache result for 10s to avoid stampede.
- **Request timeouts**: Set FastAPI request timeout to 60s; LLM/DB timeouts shorter.
- **Langfuse optional**: If keys not configured, skip tracing (don't fail).
