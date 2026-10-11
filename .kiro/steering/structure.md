# QueryPilot Project Structure

## Directory Layout

```
querypilot/
├── .kiro/
│   └── steering/                    # (this directory; project guidance)
│       ├── product.md
│       ├── tech.md
│       └── structure.md
├── app/                             # Main application code
│   ├── __init__.py
│   ├── main.py                      # FastAPI entry point
│   ├── config.py                    # Pydantic settings, env vars
│   ├── observability.py             # Langfuse setup
│   │
│   ├── api/                         # FastAPI routes
│   │   ├── __init__.py
│   │   ├── chat.py                  # POST /chat, streaming
│   │   ├── conversations.py         # GET /conversations/{id}, history
│   │   └── eval.py                  # POST /eval/run
│   │
│   ├── agent/                       # LangGraph orchestration
│   │   ├── __init__.py
│   │   ├── state.py                 # AgentState TypedDict
│   │   ├── graph.py                 # Build & wire the state machine
│   │   └── nodes/                   # Each node is a module
│   │       ├── __init__.py
│   │       ├── load_memory.py
│   │       ├── planner.py
│   │       ├── retrieve_schema.py
│   │       ├── generate_sql.py
│   │       ├── validate_sql.py
│   │       ├── execute_sql.py
│   │       ├── fix_sql.py
│   │       ├── analyze_result.py
│   │       └── save_memory.py
│   │
│   ├── prompts/                     # LLM prompt templates (versioned)
│   │   ├── __init__.py
│   │   ├── planner.txt
│   │   ├── generate_sql.txt
│   │   ├── fix_sql.txt
│   │   └── analyze_result.txt
│   │
│   ├── tools/                       # Deterministic utility functions
│   │   ├── __init__.py
│   │   ├── schema.py                # get_schema(), get_table_metadata()
│   │   ├── validator.py             # validate_sql() with sqlglot
│   │   ├── executor.py              # execute_sql() with timeout/limits
│   │   ├── history.py               # get_previous_queries()
│   │   └── exceptions.py            # ValidationError, ExecutionError, etc.
│   │
│   ├── memory/                      # Persistence layer
│   │   ├── __init__.py
│   │   ├── postgres.py              # save_query(), load_conversation()
│   │   └── redis.py                 # checkpoints, schema cache
│   │
│   └── semantic_layer.yaml          # Business term definitions
│
├── eval/                            # Evaluation harness
│   ├── __init__.py
│   ├── dataset.jsonl                # Gold queries & expected results
│   ├── run_eval.py                  # Main eval runner
│   ├── metrics.py                   # Scoring functions
│   └── failure_injection.py         # Test failure modes
│
├── seed/                            # Database seeding
│   ├── __init__.py
│   ├── schema.sql                   # DDL for e-commerce data
│   └── generator.py                 # Synthetic data generator
│
├── tests/                           # Test suite (mirrors app/)
│   ├── __init__.py
│   ├── conftest.py                  # Shared fixtures (DB, fixtures)
│   │
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── test_validator.py        # SQL injection, destructive queries
│   │   ├── test_executor.py         # Timeout, row limits
│   │   ├── test_schema.py           # Schema retrieval
│   │   └── test_exceptions.py
│   │
│   ├── agent/
│   │   ├── __init__.py
│   │   └── test_graph.py            # State transitions, routing logic
│   │
│   ├── api/
│   │   ├── __init__.py
│   │   └── test_chat.py             # Integration tests
│   │
│   └── memory/
│       ├── __init__.py
│       └── test_postgres.py
│
├── .env.example                     # Environment variable documentation
├── .gitignore
├── .dockerignore
├── docker-compose.yml               # Dev environment
├── Dockerfile
├── pyproject.toml                   # Deps, metadata, tool configs
├── README.md                        # Project overview & setup
└── docs/
    └── PLAN.md                      # Full design document

```

## Naming & File Organization Conventions

### Modules
- **One responsibility per file**. E.g., `validator.py` contains only validation logic; execution lives in `executor.py`.
- Module names are **lowercase with underscores** (`my_module.py`, not `MyModule.py`).
- **Classes**: PascalCase (`ValidationError`, `AgentState`).
- **Functions**: snake_case (`validate_sql`, `get_schema`).
- **Constants**: UPPER_SNAKE_CASE (`MAX_RETRIES`, `TIMEOUT_SECONDS`).

### Type Hints
- Use `from typing import TypedDict, Optional, Literal, Sequence, AsyncIterator` etc.
- Return types for all functions.
- No bare `dict` or `list`; use `dict[str, Any]` or `list[dict[str, str]]`.

### Test Naming
- Test files: `test_*.py` in the `tests/` directory, mirroring `app/`.
- Test functions: `test_<thing>_<scenario>`, e.g., `test_validator_rejects_drop_table`.
- Fixtures: `@pytest.fixture` with descriptive names (`target_db_conn`, `sample_schema`).

### Imports
- **Standard library** first, then **third-party**, then **local**.
- Avoid circular imports; use `TYPE_CHECKING` if needed for type hints.
- No wildcard imports (`from module import *`).

## Configuration & Secrets

### Environment Variables
Define all config in `app/config.py` using `pydantic-settings`:

```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # API
    debug: bool = False
    api_port: int = 8000
    
    # Databases
    app_db_url: str  # postgresql://user:pass@localhost/app_db
    target_db_url: str
    target_db_readonly_role: str = "readonly_user"
    
    # Agent
    max_retries: int = 3
    max_iterations: int = 10
    
    # LLM
    langchain_api_key: str
    langfuse_public_key: str
    langfuse_secret_key: str
    
    # Redis
    redis_url: str = "redis://localhost:6379"
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

settings = Settings()
```

### `.env.example`
Never commit `.env`; always commit `.env.example` with placeholder values:
```
# API
DEBUG=false
API_PORT=8000

# Databases
APP_DB_URL=postgresql://app_user:password@localhost:5432/app_db
TARGET_DB_URL=postgresql://analytics_user:password@localhost:5433/target_db
TARGET_DB_READONLY_ROLE=readonly_user

# Agent
MAX_RETRIES=3
MAX_ITERATIONS=10

# LLM
LANGCHAIN_API_KEY=sk-...
LANGFUSE_PUBLIC_KEY=pk-...
LANGFUSE_SECRET_KEY=sk-...

# Redis
REDIS_URL=redis://localhost:6379
```

## Testing Structure

### Fixture Organization
All shared fixtures in `tests/conftest.py`:
- Database connections (app_db, target_db)
- Sample schemas
- Mock LLM responses
- Cleaned-up state between tests

### Test Isolation
- Each test uses a transaction that rolls back after the test
- Or use a fresh test database and `DROP DATABASE` after
- Never share state between tests

### Coverage
- Aim for 80%+ coverage in deterministic modules (validator, executor)
- Safety-critical modules (validator) should have 100%
- Use `pytest --cov=app` to check

## Build & Deployment

### Local Development
```bash
uv sync                           # Install deps
docker-compose up -d              # Start services (PG, Redis, etc.)
alembic upgrade head              # Run migrations
python -m app.main                # Run FastAPI dev server
```

### Docker Build
- Single Dockerfile for the app
- Multi-stage build: one stage for dependencies, one for runtime
- Keep images small; no unnecessary files

### CI/CD Signals
- All tests pass (`pytest`)
- Type checking passes (`mypy app/`)
- Linting passes (`ruff check app/`)
- No unsafe SQL makes it past validation

## Documentation Standards

### Code Comments
- **Why**, not **what** (the code shows what; comments explain intent).
- Doc strings on all public functions and classes.
- Explain non-obvious type hints or complex logic.

### Module-Level Docstrings
Every module starts with a brief summary:
```python
"""
Deterministic SQL validator using sqlglot AST parsing.
Ensures all queries are SELECT-only and use allowed tables.
"""
```

### README in Each Package
- `app/tools/README.md` explains what tools are available and their contracts
- `eval/README.md` explains how to run the eval harness

## Dependencies & Versioning

All versions pinned in `pyproject.toml`. Use `uv` or `pip` to manage:
```bash
uv add fastapi==0.104.1
uv add "sqlglot>=23,<24"
uv sync
```

No `requirements.txt`; only `pyproject.toml` and `uv.lock` (committed).
