# Spec: API Service, Observability, and Deployment

## Overview

This spec covers the implementation of the FastAPI service layer for QueryPilot, including authentication, rate limiting, observability/tracing, structured logging, and Docker deployment.

## Requirements

### 1. FastAPI Endpoints

#### 1.1 POST /chat (SSE Streaming)
- **Description**: Streaming endpoint that sends node-by-node progress events
- **Authentication**: Required (X-API-Key header if enabled)
- **Request**:
  ```json
  {
    "conversation_id": "string (optional, auto-generated if not provided)",
    "user_id": "string (required)",
    "question": "string (required)"
  }
  ```
- **Response**: Server-Sent Events (SSE) stream with events:
  - `node_start`: Node execution started
  - `node_end`: Node execution completed
  - `final_answer`: Query completed with answer
  - `error`: Error occurred

#### 1.2 POST /chat/ (Non-Streaming)
- **Description**: Non-streaming endpoint that waits for full response
- **Request**: Same as /chat stream
- **Response**:
  ```json
  {
    "conversation_id": "string",
    "message_id": "string",
    "question": "string",
    "plan": ["string"],
    "sql": "string",
    "result": {...},
    "answer": "string",
    "status": "string",
    "iterations": "int",
    "retries": "int",
    "error": "string (optional)"
  }
  ```

#### 1.3 GET /conversations/{id}
- **Description**: Retrieve conversation metadata and history
- **Response**:
  ```json
  {
    "id": "string",
    "user_id": "string",
    "title": "string",
    "created_at": "ISO 8601 timestamp",
    "updated_at": "ISO 8601 timestamp",
    "message_count": "int"
  }
  ```

#### 1.4 GET /conversations/{id}/messages
- **Description**: Retrieve messages from a conversation with pagination
- **Query Parameters**:
  - `limit`: int (1-100, default 50)
  - `offset`: int (default 0)
- **Response**:
  ```json
  {
    "conversation_id": "string",
    "messages": [...],
    "total": "int",
    "limit": "int",
    "offset": "int"
  }
  ```

#### 1.5 POST /eval/run
- **Description**: Run evaluation harness against dataset
- **Request**:
  ```json
  {
    "system": "baseline|agent",
    "semantic_layer": "bool",
    "retries_enabled": "bool",
    "memory_enabled": "bool",
    "failures": "on|off",
    "dataset_path": "string (optional)"
  }
  ```
- **Response**:
  ```json
  {
    "run_id": "string",
    "status": "completed|failed",
    "system": "string",
    "config": {...},
    "metrics": {...},
    "report_path": "string"
  }
  ```

#### 1.6 GET /health
- **Description**: Health check endpoint
- **No Auth Required**
- **Response**:
  ```json
  {
    "status": "ok",
    "service": "QueryPilot",
    "version": "0.1.0"
  }
  ```

### 2. Authentication & Authorization

#### 2.1 API Key Authentication
- **Header**: `X-API-Key`
- **Configuration**:
  - `REQUIRE_API_KEY`: Boolean (default: false)
  - `API_KEY`: Secret key for validation
- **Behavior**:
  - If `REQUIRE_API_KEY=true`, all endpoints except `/health` require valid `X-API-Key` header
  - Returns `401 Unauthorized` if header missing
  - Returns `403 Forbidden` if key invalid
  - Health check endpoint never requires auth

#### 2.2 User Identification
- **Header**: `X-User-ID` (optional)
- **Behavior**:
  - If provided, used for rate limiting and user-scoped metrics
  - If not provided, defaults to "anonymous"
  - Included in all request logs and traces

### 3. Rate Limiting

#### 3.1 Configuration
- **Environment Variable**: `RATE_LIMIT_REQUESTS_PER_MINUTE` (default: 60)
- **Scope**: Per user (via `X-User-ID` header)
- **Window**: 1 minute (rolling)
- **Backend**: Redis

#### 3.2 Behavior
- Each user gets `RATE_LIMIT_REQUESTS_PER_MINUTE` requests per minute
- Health check endpoint exempt from rate limiting
- Rate limit key: `user:{user_id}:requests:{minute}`
- Redis TTL: 60 seconds
- Returns `429 Too Many Requests` when exceeded

#### 3.3 Response Headers
- `X-RateLimit-Limit`: Max requests per minute
- `X-RateLimit-Remaining`: Requests remaining in window
- `X-RateLimit-Reset`: Unix timestamp when limit resets

### 4. Request Tracking

#### 4.1 Request IDs
- **Generation**: UUID v4 for each request
- **Propagation**: All logs and traces include request ID
- **Response Header**: `X-Request-ID`
- **Context Variable**: `request_id_context` (ContextVar)

#### 4.2 Request Context
- **Request ID**: Unique identifier for the request
- **User ID**: From `X-User-ID` header or "anonymous"
- **Start Time**: Timestamp when request started
- **Duration**: Elapsed time for request

### 5. Structured Logging

#### 5.1 Format
- **Type**: JSON
- **Fields**:
  - `timestamp`: ISO 8601 timestamp
  - `level`: Log level (INFO, ERROR, etc.)
  - `logger`: Logger name
  - `message`: Log message
  - `request_id`: Request ID (if in request context)
  - `user_id`: User ID (if in request context)
  - `exception`: Exception traceback (if error)

#### 5.2 Configuration
- **Environment Variable**: `DEBUG` (default: false)
- **Log Level**: INFO if DEBUG=false, DEBUG if DEBUG=true
- **Output**: stdout (JSON format in production, readable format in dev)

#### 5.3 Log Events
- `request_start`: New incoming request
- `request_end`: Request completed with status code and duration
- `auth_missing`: API key header missing
- `auth_invalid`: Invalid API key provided
- `rate_limit_exceeded`: User rate limit exceeded
- `chat_request`: Chat request received
- `chat_error`: Error during chat processing
- `get_conversation`: Conversation retrieval request
- `get_conversation_error`: Error retrieving conversation
- `get_messages`: Message retrieval request
- `get_messages_error`: Error retrieving messages
- `eval_run_start`: Evaluation run started
- `eval_run_error`: Error during evaluation

### 6. Langfuse Observability

#### 6.1 Configuration
- **Environment Variables**:
  - `LANGFUSE_PUBLIC_KEY`: Public API key
  - `LANGFUSE_SECRET_KEY`: Secret API key
  - `LANGFUSE_HOST`: Langfuse server URL (optional)
- **Behavior**:
  - Disabled if keys not provided (graceful degradation)
  - Lazy initialization on first use

#### 6.2 Trace Structure
Per request:
- **Trace Name**: Request type (e.g., "chat_request", "eval_run")
- **User ID**: User making the request
- **Session ID**: Request ID for correlation
- **Spans**:
  - Per LangGraph node: name, type, input/output
  - Per LLM call: model, prompt, completion, tokens, cost
  - Per tool call: tool name, parameters, result
- **Metadata**:
  - `request_id`: Request ID
  - `user_id`: User ID
  - `conversation_id`: Conversation ID (if applicable)
  - `endpoint`: API endpoint called
  - `timestamp`: Event timestamp

#### 6.3 LLM Metrics
- **Model**: Model name (e.g., "gpt-4-turbo")
- **Prompt Tokens**: Input token count
- **Completion Tokens**: Output token count
- **Cost**: Estimated cost in USD

### 7. Docker & Deployment

#### 7.1 Services
- **api**: FastAPI application (port 8000)
- **app_db**: PostgreSQL for app metadata (port 5432)
- **target_db**: PostgreSQL for analytics data (port 5433)
- **redis**: Redis cache (port 6379)
- **langfuse**: Observability platform (port 3000)
- **langfuse_db**: Langfuse database (internal)

#### 7.2 Environment Variables
All passed via `.env` file:
```bash
DEBUG=false
API_PORT=8000
API_HOST=0.0.0.0
API_KEY=your-secret-key
REQUIRE_API_KEY=false
RATE_LIMIT_REQUESTS_PER_MINUTE=60
APP_DB_URL=postgresql://app_user:app_password@app_db:5432/querypilot_app
TARGET_DB_URL=postgresql://querypilot_ro:readonly_password@target_db:5432/querypilot_target
TARGET_DB_READONLY_ROLE=querypilot_ro
LLM_PROVIDER=openai
LLM_MODEL=gpt-4-turbo
OPENAI_API_KEY=sk-...
LANGFUSE_PUBLIC_KEY=pk-...
LANGFUSE_SECRET_KEY=sk-...
REDIS_URL=redis://redis:6379
MEMORY_HISTORY_LIMIT=10
MEMORY_LONG_TERM_ENABLED=false
```

#### 7.3 Startup
```bash
docker-compose up -d
```

This will:
1. Build the API image
2. Start all services (databases, Redis, Langfuse)
3. Wait for health checks to pass
4. Seed data into target_db (via seed/init_app_db.sh)
5. API available at http://localhost:8000
6. Docs at http://localhost:8000/docs
7. Langfuse at http://localhost:3000

#### 7.4 Health Checks
- **api**: HTTP GET /health (200 OK expected)
- **app_db**: psycopg2 connection check
- **target_db**: psycopg2 connection check
- **redis**: redis-cli PING
- **langfuse**: HTTP GET /health

### 8. Middleware Stack

#### Order (innermost to outermost)
1. **RequestIDMiddleware**: Generate and attach request ID
2. **StructuredLoggingMiddleware**: Log all requests with context
3. **RateLimitMiddleware**: Check rate limits per user
4. **APIKeyAuthMiddleware**: Validate API key
5. **CORSMiddleware**: Handle CORS

## Implementation

### Files to Create/Modify

- `app/middleware.py` ✓ (new)
  - RequestIDMiddleware
  - StructuredLoggingMiddleware
  - RateLimitMiddleware
  - APIKeyAuthMiddleware
  - Context getters

- `app/observability.py` ✓ (modified)
  - StructuredFormatter
  - setup_structured_logging()
  - get_langfuse_client()
  - trace_request()
  - trace_span()
  - trace_llm_call()

- `app/main.py` ✓ (modified)
  - Middleware integration
  - Health check enhancement
  - Structured logging setup

- `app/config.py` ✓ (modified)
  - API_KEY
  - REQUIRE_API_KEY
  - RATE_LIMIT_REQUESTS_PER_MINUTE
  - CORS_ALLOWED_ORIGINS
  - LANGFUSE_HOST

- `app/api/chat.py` ✓ (modified)
  - ChatRequest model
  - ChatEvent model
  - ChatResponse model
  - stream_chat_events() async generator
  - POST /chat/stream endpoint
  - POST /chat/ endpoint

- `app/api/conversations.py` ✓ (modified)
  - GET /conversations/{id}
  - GET /conversations/{id}/messages
  - Message model

- `app/api/eval.py` ✓ (modified)
  - EvalRunRequest model
  - EvalMetrics model
  - EvalRunResponse model
  - POST /eval/run endpoint

- `.env.example` ✓ (modified)
  - All new configuration variables

- `tests/api/test_chat.py` ✓ (new)
  - TestChatStream
  - TestChatNonStreaming

- `tests/api/test_auth_and_limits.py` ✓ (new)
  - TestAPIKeyAuth
  - TestRateLimiting
  - TestRequestID

- `tests/api/__init__.py` ✓ (new)

## Testing

### Unit Tests
```bash
pytest tests/api/ -v
```

### Test Coverage
- ✓ Chat streaming endpoint
- ✓ Chat non-streaming endpoint
- ✓ API key auth: missing, invalid, valid
- ✓ Rate limiting: under limit, over limit, per user
- ✓ Request ID: generation, propagation, uniqueness
- ✓ Conversation retrieval
- ✓ Message pagination
- ✓ Evaluation runner

### Manual Testing
```bash
# Health check
curl http://localhost:8000/health

# Chat endpoint (with auth disabled)
curl -X POST http://localhost:8000/chat/ \
  -H "Content-Type: application/json" \
  -d '{"user_id": "test", "question": "Top customers?"}'

# Stream endpoint
curl -X POST http://localhost:8000/chat/stream \
  -H "Content-Type: application/json" \
  -d '{"user_id": "test", "question": "Top customers?"}' \
  -H "Accept: text/event-stream"

# With API key
curl -X POST http://localhost:8000/chat/ \
  -H "X-API-Key: your-secret-key" \
  -H "Content-Type: application/json" \
  -d '{"user_id": "test", "question": "Top customers?"}'
```

## Production Checklist

- [ ] Set `DEBUG=false`
- [ ] Set `REQUIRE_API_KEY=true` and provide `API_KEY`
- [ ] Configure `CORS_ALLOWED_ORIGINS` to trusted domains
- [ ] Set up Langfuse keys for tracing
- [ ] Configure `RATE_LIMIT_REQUESTS_PER_MINUTE` based on capacity
- [ ] Ensure Redis is running and accessible
- [ ] Run database migrations: `alembic upgrade head`
- [ ] Seed target database with data
- [ ] Test `/health` endpoint responds
- [ ] Verify logs are structured JSON
- [ ] Test rate limiting
- [ ] Monitor Langfuse traces
- [ ] Set up log aggregation (e.g., ELK, CloudWatch)
- [ ] Configure alerting on error rates

## Future Enhancements

- OAuth2 / OIDC support
- API key scopes and permissions
- Request/response logging to database
- Metrics export (Prometheus)
- WebSocket support for chat (instead of SSE)
- Circuit breaker for database/external services
- Request replay/testing tools
- Audit logging for security events
