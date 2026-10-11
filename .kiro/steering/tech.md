# QueryPilot Tech Stack & Rules

## Core Dependencies
- **Python 3.11+**
- **FastAPI** – REST API with async support
- **LangGraph** – state machine for agent orchestration
- **sqlglot** – SQL parsing and validation (deterministic safety layer)
- **psycopg** (3.x) – PostgreSQL driver with async support
- **pydantic** (v2) – settings, validation, serialization
- **pydantic-settings** – environment-based config
- **pytest** – unit and integration tests
- **pytest-asyncio** – async test support
- **Redis** – LangGraph checkpoints, schema cache, rate limits
- **PostgreSQL 16** – two separate instances:
  - **App DB**: conversations, query_log, eval_runs, auth
  - **Target DB**: analytics data (SELECT-only role)
- **pgvector** – semantic search for large schemas
- **Langfuse** – trace collection and observability
- **Docker & Docker Compose** – containerized dev environment
- **Next.js** (optional, last priority) – chat UI

## Environment-Based Configuration
- **All secrets and config via environment variables**, never hardcoded
- Use `.env.example` as documentation
- Load via `pydantic-settings.BaseSettings`
- Never log sensitive values (API keys, connection strings, tokens)

## Code Quality Rules
1. **Type hints everywhere**
   - Function signatures: all params and return types
   - Class attributes: use TypedDict, dataclass, or Pydantic model
   - No implicit `Any`; use it only when absolutely necessary with a comment

2. **Async/await**
   - Database queries: async with psycopg
   - LangGraph callbacks: async where applicable
   - FastAPI endpoints: async by default

3. **Testing**
   - Unit tests for validation, executor, schema retrieval
   - Parametrized tests for SQL injection, destructive queries
   - 100% block rate for unsafe SQL should be verified in tests
   - Use pytest fixtures for DB setup/teardown

4. **Error handling**
   - Specific exception types (e.g., `ValidationError`, `ExecutionError`, `SchemaError`)
   - User-facing errors: sanitized, no stack traces
   - Logging: errors with context but never secrets

5. **Observability**
   - LangGraph events to Langfuse
   - All tool calls logged (schema retrieval, validation, execution)
   - Query latency, token count, cost tracked
   - No PII or sensitive data in logs/traces

## Dependency Management
Use `uv` (or `pip` with pinned versions):
```
python -m pip install uv
uv sync  # install from pyproject.toml
```

All versions in `pyproject.toml` should be exact or conservative:
- Core: exact (e.g., `fastapi==0.104.1`)
- Libraries: minor-compatible (e.g., `sqlglot>=23,<24`)
- Dev: loose if not impacting runtime (e.g., `pytest>=7`)

## Database Roles & Security
### App DB (PostgreSQL 16)
- Default role: read-write for app metadata
- Connections pooled via PgBouncer if needed

### Target DB (PostgreSQL 16)
- Create a **read-only role**: `GRANT SELECT ON ALL TABLES IN SCHEMA public TO readonly_user;`
- Connect as `readonly_user` for all queries
- Enforce: `SET TRANSACTION READ ONLY;` on every query
- Set `statement_timeout = '5s'` to prevent runaway queries
- Never allow the app role to have INSERT/UPDATE/DELETE

## Project Layout
See `structure.md` for full layout. Key rule:
- Tests in `tests/` mirror `app/` structure exactly
- E.g., `app/tools/validator.py` ↔ `tests/tools/test_validator.py`

## Docker Compose
One image for the FastAPI app, separate services for PostgreSQL (app), PostgreSQL (target), Redis, and Langfuse.
- Env vars passed via `.env` file or `docker-compose.override.yml`
- Health checks on all services
- No hardcoded ports; make them configurable

## Logging & Tracing
- **Standard library `logging`** for application logs
- **Langfuse** for LLM traces (prompt, completion, tool calls, latency)
- **Query log** table in App DB for durability
- Structured logs: JSON format for easier parsing
