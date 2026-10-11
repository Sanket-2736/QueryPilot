# QueryPilot API Service & Deployment Guide

## Overview

This guide covers deploying QueryPilot's FastAPI service with observability, authentication, rate limiting, and Docker containerization.

## Quick Start

### Prerequisites
- Docker and Docker Compose
- Python 3.11+ (for local development)
- PostgreSQL 16 (for local development)

### Local Development

```bash
# Install dependencies
uv sync

# Copy environment template
cp .env.example .env

# Edit .env with your configuration
# (at minimum: LLM provider keys)

# Start services
docker-compose up -d

# Run migrations
alembic upgrade head

# Seed data
python -m seed.generator --customers 100 --orders 500

# Start API server
python -m app.main
```

API available at http://localhost:8000
API docs at http://localhost:8000/docs

### Docker Deployment

```bash
# Build and start all services
docker-compose up -d

# Check status
docker-compose ps

# View logs
docker-compose logs -f api

# Stop services
docker-compose down

# Clean up volumes
docker-compose down -v
```

## API Endpoints

### Chat Endpoints

#### Streaming Chat (Server-Sent Events)
```bash
curl -X POST http://localhost:8000/chat/stream \
  -H "Content-Type: application/json" \
  -H "X-User-ID: user_123" \
  -d '{
    "question": "What are the top 5 customers by revenue?"
  }' \
  -H "Accept: text/event-stream"
```

Real-time event stream:
```
data: {"event_type": "node_start", "node_name": "planner", ...}
data: {"event_type": "node_end", "node_name": "planner", ...}
...
data: {"event_type": "final_answer", "data": {"answer": "..."}}
```

#### Non-Streaming Chat
```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -H "X-User-ID: user_123" \
  -d '{
    "conversation_id": "conv_123",
    "user_id": "user_123",
    "question": "Top 5 customers by revenue?"
  }'
```

Response:
```json
{
  "conversation_id": "conv_123",
  "message_id": "msg_456",
  "question": "Top 5 customers by revenue?",
  "plan": ["Retrieve schema", "Generate SQL", "Execute", "Analyze"],
  "sql": "SELECT c.id, SUM(o.total) FROM customers c...",
  "result": {
    "columns": ["id", "sum"],
    "rows": [[1, 50000], [2, 45000], ...]
  },
  "answer": "The top 5 customers by revenue are...",
  "status": "answered",
  "iterations": 5,
  "retries": 0
}
```

### Conversation Endpoints

#### Get Conversation
```bash
curl http://localhost:8000/conversations/conv_123 \
  -H "X-User-ID: user_123"
```

Response:
```json
{
  "id": "conv_123",
  "user_id": "user_123",
  "title": "Revenue Analysis",
  "created_at": "2024-01-01T00:00:00Z",
  "updated_at": "2024-01-02T12:30:00Z",
  "message_count": 5
}
```

#### Get Messages
```bash
curl "http://localhost:8000/conversations/conv_123/messages?limit=20&offset=0" \
  -H "X-User-ID: user_123"
```

Response:
```json
{
  "conversation_id": "conv_123",
  "messages": [
    {
      "id": "msg_1",
      "turn_number": 1,
      "question": "Top customers?",
      "answer": "...",
      "sql": "SELECT * FROM customers...",
      "status": "answered",
      "iterations": 4,
      "retries": 0
    }
  ],
  "total": 3,
  "limit": 20,
  "offset": 0
}
```

### Evaluation Endpoints

#### Run Evaluation
```bash
curl -X POST http://localhost:8000/eval/run \
  -H "Content-Type: application/json" \
  -d '{
    "system": "agent",
    "semantic_layer": true,
    "retries_enabled": true,
    "memory_enabled": true,
    "failures": "off"
  }'
```

Response:
```json
{
  "run_id": "eval_789",
  "status": "completed",
  "system": "agent",
  "config": {...},
  "metrics": {
    "execution_accuracy": 0.95,
    "answer_accuracy": 0.92,
    "schema_retrieval_recall": 0.88,
    "retry_success_rate": 0.80,
    "avg_iterations": 5.2,
    "p50_latency_ms": 1240.0,
    "p95_latency_ms": 3100.0,
    "avg_tokens_per_query": 285.0,
    "avg_cost_cents": 0.0142,
    "unsafe_query_block_rate": 1.0,
    "total_queries": 60,
    "failed_queries": 3
  },
  "report_path": "eval/reports/eval_agent_789.md"
}
```

### Health Check
```bash
curl http://localhost:8000/health
```

Response:
```json
{
  "status": "ok",
  "service": "QueryPilot",
  "version": "0.1.0"
}
```

## Authentication & Security

### API Key Authentication

Enable in `.env`:
```bash
REQUIRE_API_KEY=true
API_KEY=your-secret-api-key-here
```

Include in requests:
```bash
curl -X POST http://localhost:8000/chat \
  -H "X-API-Key: your-secret-api-key-here" \
  -H "Content-Type: application/json" \
  -d '{...}'
```

### Rate Limiting

Configure in `.env`:
```bash
RATE_LIMIT_REQUESTS_PER_MINUTE=60
```

Per-user rate limiting via `X-User-ID` header:
```bash
curl -X POST http://localhost:8000/chat \
  -H "X-User-ID: user_123" \
  -H "Content-Type: application/json" \
  -d '{...}'
```

Rate limit exceeded response:
```json
{
  "detail": "Rate limit exceeded",
  "limit": 60,
  "window": "1 minute"
}
```

## Observability

### Request Tracking

Every request gets a unique ID:
```bash
curl http://localhost:8000/health -v
# X-Request-ID: 550e8400-e29b-41d4-a716-446655440000
```

### Structured Logging

JSON logs with full context:
```json
{
  "timestamp": "2024-01-01T12:00:00",
  "level": "INFO",
  "logger": "app.api.chat",
  "message": "Chat request received",
  "request_id": "550e8400-e29b-41d4-a716-446655440000",
  "user_id": "user_123",
  "conversation_id": "conv_123"
}
```

### Langfuse Tracing

Enable in `.env`:
```bash
LANGFUSE_PUBLIC_KEY=pk-...
LANGFUSE_SECRET_KEY=sk-...
LANGFUSE_HOST=http://langfuse:3000
```

Traces captured for:
- Each API request
- Each LangGraph node execution
- Each LLM call (prompt, completion, tokens, cost)
- Each tool call (schema, validation, execution)

View traces at http://localhost:3000

## Configuration

### Environment Variables

#### API Configuration
```bash
DEBUG=false                              # Debug mode
API_PORT=8000                            # Port to listen on
API_HOST=0.0.0.0                         # Bind address
API_KEY=your-secret-api-key-here         # API key
REQUIRE_API_KEY=false                    # Require auth
RATE_LIMIT_REQUESTS_PER_MINUTE=60        # Per-user rate limit
CORS_ALLOWED_ORIGINS=["*"]               # CORS allowed origins
```

#### Database Configuration
```bash
APP_DB_URL=postgresql://user:pass@localhost/app_db
TARGET_DB_URL=postgresql://user:pass@localhost/target_db
TARGET_DB_READONLY_ROLE=readonly_user
```

#### Agent Configuration
```bash
MAX_RETRIES=3
MAX_ITERATIONS=10
QUERY_TIMEOUT_SECONDS=5
RESULT_ROW_LIMIT=1000
```

#### LLM Configuration
```bash
LLM_PROVIDER=openai                      # openai, anthropic, or bedrock
LLM_MODEL=gpt-4-turbo
LLM_TEMPERATURE=0.0
LLM_MAX_TOKENS=2048
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
```

#### Observability
```bash
LANGFUSE_PUBLIC_KEY=pk-...
LANGFUSE_SECRET_KEY=sk-...
LANGFUSE_HOST=http://localhost:3000
```

#### Memory
```bash
REDIS_URL=redis://localhost:6379
MEMORY_HISTORY_LIMIT=10
MEMORY_LONG_TERM_ENABLED=false
MEMORY_EMBEDDING_MODEL=text-embedding-3-small
MEMORY_SIMILARITY_THRESHOLD=0.6
MEMORY_SUMMARY_THRESHOLD=20
```

## Testing

### Run Test Suite
```bash
pytest tests/api/ -v
```

### Test Chat Endpoint
```bash
pytest tests/api/test_chat.py::TestChatStream::test_chat_stream_success -v
```

### Test Authentication
```bash
pytest tests/api/test_auth_and_limits.py::TestAPIKeyAuth -v
```

### Test Rate Limiting
```bash
pytest tests/api/test_auth_and_limits.py::TestRateLimiting -v
```

## Monitoring & Debugging

### Check Service Status
```bash
docker-compose ps
```

### View Logs
```bash
# All services
docker-compose logs -f

# Specific service
docker-compose logs -f api
docker-compose logs -f app_db
docker-compose logs -f redis
```

### Connect to Databases
```bash
# App DB
psql -h localhost -U app_user -d querypilot_app

# Target DB
psql -h localhost -p 5433 -U analytics_user -d querypilot_target
```

### Check Redis
```bash
redis-cli -h localhost -p 6379
# PING
# KEYS *
# GET user:user_123:requests:*
```

### View Traces
Open browser: http://localhost:3000

## Performance Tuning

### Database Optimization
```bash
# App DB: Increase max connections
# docker-compose.yml: postgres environment
POSTGRES_INITDB_ARGS="-c max_connections=200"

# Target DB: Read-only query optimization
SET default_statistics_target = 100;
ANALYZE;
```

### Redis Optimization
```bash
# Monitor memory usage
redis-cli INFO memory

# Increase maxmemory policy
redis-cli CONFIG SET maxmemory-policy allkeys-lru
```

### API Optimization
```bash
# Increase rate limit for trusted users
RATE_LIMIT_REQUESTS_PER_MINUTE=120

# Adjust worker count in uvicorn
# docker-compose.yml: api command
CMD ["uvicorn", "app.main:app", "--workers", "4", "--host", "0.0.0.0", "--port", "8000"]
```

## Production Deployment

### Kubernetes Deployment
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: querypilot-api
spec:
  replicas: 3
  selector:
    matchLabels:
      app: querypilot-api
  template:
    metadata:
      labels:
        app: querypilot-api
    spec:
      containers:
      - name: api
        image: querypilot:latest
        ports:
        - containerPort: 8000
        env:
        - name: DEBUG
          value: "false"
        - name: REQUIRE_API_KEY
          value: "true"
        - name: RATE_LIMIT_REQUESTS_PER_MINUTE
          value: "100"
        livenessProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 30
          periodSeconds: 10
        readinessProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 10
          periodSeconds: 5
```

### Environment Secrets
```bash
# Use environment-specific .env files
.env.development
.env.staging
.env.production

# Or use secret management:
# - AWS Secrets Manager
# - HashiCorp Vault
# - Kubernetes Secrets
```

### Monitoring & Alerting
```bash
# Prometheus metrics
# Configure scrape job for /metrics endpoint

# CloudWatch logs
# Stream logs to CloudWatch

# Datadog integration
# Configure Datadog agent for APM tracing
```

## Troubleshooting

### Service won't start
```bash
# Check logs
docker-compose logs api

# Verify environment variables
grep API_PORT .env

# Test connectivity
docker-compose exec api curl http://localhost:8000/health
```

### Rate limiting not working
```bash
# Check Redis connection
redis-cli -h redis ping

# Monitor rate limit keys
redis-cli MONITOR | grep "user:.*:requests"

# Check rate limit configuration
grep RATE_LIMIT .env
```

### Auth not working
```bash
# Verify API key configuration
grep API_KEY .env

# Test with curl
curl -H "X-API-Key: $(grep API_KEY .env | cut -d= -f2)" http://localhost:8000/health
```

### Database connection issues
```bash
# Check database URLs
grep DB_URL .env

# Test connection
docker-compose exec api psql $(grep APP_DB_URL .env | cut -d= -f2) -c "SELECT 1"
```

## See Also

- [PROJECT_PLAN.md](../docs/PROJECT_PLAN.md) - Full project plan
- [README.md](../README.md) - Project overview
- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [Langfuse Documentation](https://docs.langfuse.com/)
- [Docker Compose Documentation](https://docs.docker.com/compose/)
