# QueryPilot: Text-to-SQL Agent for Business Analytics

A stateful, deterministic text-to-SQL agent that turns natural language questions into safe, validated SQL queries. Built with LangGraph for orchestration, sqlglot for safety validation, and PostgreSQL for data.

## Problem

Business users (ops, sales, finance) cannot write SQL and need answers from relational databases. A single LLM call fails because models:
- **Hallucinate schema** (invent columns/tables that don't exist)
- **Produce incorrect joins** (double-counting, wrong cardinality)
- **Generate invalid SQL** (syntax errors, missing tables)
- **Lack safety guardrails** (can execute DROP TABLE, DELETE, etc.)
- **Can't handle ambiguity** (revenue = gross? net? paid-only?)
- **Have no memory** across multi-turn conversations

## Solution

A **stateful text-to-SQL agent** that:
- Breaks questions into steps via a planner
- Retrieves only relevant schema (deterministic, no hallucination)
- Generates SQL with schema context and conversation history
- **Validates using deterministic Python code** (sqlglot AST parsing), not LLM judgment
- Executes read-only against a separate target database
- Recovers from errors via fix/retry or replanning
- Remembers context across conversation turns
- Explains results and flags anomalies

## Tech Stack

- **Python 3.11+**
- **FastAPI** – REST API with async support
- **LangGraph** – state machine orchestration
- **sqlglot** – SQL parsing and safety validation (deterministic layer)
- **PostgreSQL 16** – two instances:
  - **App DB**: conversations, query_log, eval_runs
  - **Target DB**: analytics data (read-only role)
- **Redis** – LangGraph checkpoints and schema cache
- **Langfuse** – trace collection and observability
- **Docker Compose** – containerized dev environment

## Quick Start

### Prerequisites
- Python 3.11+
- PostgreSQL 16 (or Docker)
- Redis (or Docker)
- `uv` package manager (or `pip`)

### Local Development

```bash
# Install dependencies
uv sync

# Start services (PostgreSQL, Redis, etc.)
docker-compose up -d

# Run migrations
alembic upgrade head

# Seed sample data (e-commerce schema)
python -m seed.generator --customers 100 --orders 500

# Start API server
python -m app.main

# In another terminal, test the agent
python -m scripts.ask "What are the top 5 customers by revenue?"
```

Visit http://localhost:8000/docs for API documentation.

### Environment Configuration

Copy `.env.example` to `.env` and update:

```bash
# Databases
APP_DB_URL=postgresql://app_user:password@localhost:5432/app_db
TARGET_DB_URL=postgresql://analytics_user:password@localhost:5433/target_db
TARGET_DB_READONLY_ROLE=readonly_user

# LLM & Observability
LANGCHAIN_API_KEY=sk-...
LANGFUSE_PUBLIC_KEY=pk-...
LANGFUSE_SECRET_KEY=sk-...

# Agent
MAX_RETRIES=3
MAX_ITERATIONS=10
```

## API Endpoints

### Chat Endpoint
```bash
POST /chat
Content-Type: application/json

{
  "conversation_id": "conv_123",
  "user_id": "user_456",
  "question": "Top 5 customers by revenue in 2024"
}
```

### Get Conversation History
```bash
GET /conversations/{conversation_id}
```

### Run Evaluation
```bash
POST /eval/run
Content-Type: application/json

{
  "system": "agent",
  "semantic_layer": true,
  "retries_enabled": true,
  "memory_enabled": true
}
```

## Agent Architecture

The agent is a LangGraph state machine with 10 nodes:

1. **load_memory** – Retrieve conversation history and long-term memory
2. **planner** – Break question into steps; detect ambiguity
3. **retrieve_schema** – Get relevant tables and columns (deterministic)
4. **generate_sql** – LLM generates SQL with schema context
5. **validate_sql** – Deterministic validation (sqlglot AST parsing)
   - Reject destructive queries (DROP, DELETE, UPDATE, INSERT)
   - Check table/column existence
   - Detect fan-out joins
6. **execute_sql** – Run read-only query with timeout (5s) and row limits
7. **fix_sql** – If validation/execution fails, LLM fixes it (up to 3 retries)
8. **analyze_result** – Check for anomalies; format answer
9. **final_answer** – Return status, SQL, result, and explanation
10. **save_memory** – Persist turn to conversation history and long-term memory

**Deterministic Safety Layer**:
- Everything that must be deterministic (validation, execution limits) lives in plain Python, not LLM logic
- Validator uses sqlglot AST parsing, not regex
- Read-only enforced by database role + connection timeout
- Schema retrieval is deterministic (no hallucination)

## Evaluation & Metrics

### Dataset

`eval/dataset.jsonl` contains 60+ test items across categories:

- **Simple Aggregation** (9 items): COUNT, SUM, AVG, GROUP BY
- **Joins** (15 items): INNER/LEFT/RIGHT/CROSS joins with fan-out detection
- **Time Comparison** (8 items): YoY, QoQ, trending
- **Follow-ups** (4 items): Multi-turn conversations with prior context
- **Ambiguous** (4 items): Questions requiring clarification
- **Adversarial** (7 items): DROP, DELETE, UPDATE, INSERT, system catalog, dangerous functions

Each item includes:
- `question`: Natural language query
- `gold_sql`: Expected SQL
- `expected_tables`: Schema needed
- `prior_turn` (optional): Previous turn for multi-turn tests
- `should_reject` (optional): True if query must be blocked

### Running Evaluation

```bash
# Baseline: execute gold SQL only
python -m eval.run_eval --system baseline

# Agent with all features
python -m eval.run_eval --system agent

# Agent without semantic layer
python -m eval.run_eval --system agent --semantic-layer off

# Agent without retries
python -m eval.run_eval --system agent --retries off

# Inject failure modes (for robustness testing)
python -m eval.run_eval --system agent --failures on

# Full A/B test: baseline vs agent
python -m eval.run_eval --system baseline
python -m eval.run_eval --system agent
```

Reports are saved to `eval/reports/<timestamp>.md` with:
- Key metrics table (accuracy, latency, cost, safety)
- Results by category
- Failed queries and error analysis

### Metrics

| Metric | Baseline | Agent |
|--------|----------|-------|
| Execution Accuracy | Pending | Pending |
| Answer Accuracy | Pending | Pending |
| Schema Retrieval Recall | N/A | Pending |
| Retry Success Rate | N/A | Pending |
| Avg Iterations | 1 | Pending |
| p50 Latency (ms) | Pending | Pending |
| p95 Latency (ms) | Pending | Pending |
| Avg Tokens/Query | 0 | Pending |
| Avg Cost (¢) | $0 | Pending |
| Safety Block Rate | N/A | 100% |
| Total Queries | 60 | 60 |

**Note**: Run `python -m eval.run_eval --system baseline` and `python -m eval.run_eval --system agent` to populate real metrics above.

## Database Schema

### App DB (PostgreSQL 16)

```sql
-- Conversations: multi-turn threads
CREATE TABLE conversations (
  id VARCHAR(36) PRIMARY KEY,
  user_id VARCHAR(255) NOT NULL,
  title VARCHAR(500),
  created_at TIMESTAMP DEFAULT NOW(),
  updated_at TIMESTAMP DEFAULT NOW()
);

-- Messages: individual turns
CREATE TABLE messages (
  id VARCHAR(36) PRIMARY KEY,
  conversation_id VARCHAR(36) REFERENCES conversations(id) ON DELETE CASCADE,
  turn_number INTEGER NOT NULL,
  question TEXT NOT NULL,
  plan JSON,
  sql TEXT,
  status VARCHAR(50),  -- answered, rejected, failed, needs_clarification
  answer TEXT,
  error TEXT,
  iterations_used INTEGER,
  retries_used INTEGER,
  created_at TIMESTAMP DEFAULT NOW()
);

-- Query log: execution details
CREATE TABLE query_log (
  id VARCHAR(36) PRIMARY KEY,
  conversation_id VARCHAR(36) REFERENCES conversations(id),
  sql TEXT NOT NULL,
  result_summary JSON,
  success BOOLEAN NOT NULL,
  error TEXT,
  latency_ms INTEGER,
  tokens_used INTEGER,
  cost_cents FLOAT,
  created_at TIMESTAMP DEFAULT NOW()
);

-- Evaluation runs: A/B test results
CREATE TABLE eval_runs (
  id VARCHAR(36) PRIMARY KEY,
  name VARCHAR(255) NOT NULL,
  config JSON,
  total_questions INTEGER,
  succeeded_count INTEGER,
  failed_count INTEGER,
  accuracy FLOAT,
  avg_latency_ms FLOAT,
  total_tokens INTEGER,
  total_cost_cents FLOAT,
  created_at TIMESTAMP DEFAULT NOW()
);

-- Long-term memory: successful queries for few-shot learning
CREATE TABLE long_term_memory (
  id VARCHAR(36) PRIMARY KEY,
  conversation_id VARCHAR(36) REFERENCES conversations(id),
  question TEXT,
  sql TEXT,
  category VARCHAR(100),
  success_rate FLOAT DEFAULT 1.0,
  usage_count INTEGER DEFAULT 1,
  created_at TIMESTAMP DEFAULT NOW()
);
```

### Target DB (PostgreSQL 16)

Read-only analytics schema (e-commerce example):

```sql
-- Seed data with realistic cardinality:
-- - 100 customers
-- - 500 orders
-- - 50 products
-- - 1000+ order items

CREATE TABLE customers (
  id INTEGER PRIMARY KEY,
  name VARCHAR(255),
  email VARCHAR(255),
  segment VARCHAR(50),  -- gold, silver, bronze
  created_at DATE
);

CREATE TABLE products (
  id INTEGER PRIMARY KEY,
  name VARCHAR(255),
  category VARCHAR(100),
  price DECIMAL(10, 2)
);

CREATE TABLE orders (
  id INTEGER PRIMARY KEY,
  customer_id INTEGER REFERENCES customers(id),
  date DATE,
  total DECIMAL(10, 2),
  status VARCHAR(50)  -- pending, shipped, delivered
);

CREATE TABLE order_items (
  id INTEGER PRIMARY KEY,
  order_id INTEGER REFERENCES orders(id),
  product_id INTEGER REFERENCES products(id),
  quantity INTEGER,
  unit_price DECIMAL(10, 2)
);

-- Read-only role
CREATE ROLE readonly_user WITH LOGIN PASSWORD 'readonly_password';
GRANT CONNECT ON DATABASE target_db TO readonly_user;
GRANT USAGE ON SCHEMA public TO readonly_user;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO readonly_user;
```

## Project Structure

```
querypilot/
├── app/                         # Main application
│   ├── api/                     # FastAPI endpoints
│   ├── agent/                   # LangGraph state machine
│   │   └── nodes/               # 10 nodes
│   ├── tools/                   # Deterministic utilities (validator, executor, schema)
│   ├── memory/                  # Persistence (PostgreSQL, Redis)
│   ├── prompts/                 # Versioned LLM prompts
│   ├── config.py                # Pydantic settings
│   ├── main.py                  # FastAPI entry point
│   └── observability.py         # Langfuse setup
│
├── eval/                        # Evaluation harness
│   ├── dataset.jsonl            # 60+ test cases
│   ├── metrics.py               # Metric computation
│   ├── failure_injection.py     # Failure mode injection
│   ├── run_eval.py              # Main eval runner
│   └── reports/                 # Markdown reports
│
├── tests/                       # Test suite (pytest)
│   ├── agent/
│   ├── tools/
│   ├── memory/
│   └── api/
│
├── scripts/                     # Utility scripts
│   └── ask.py                   # CLI for testing
│
├── seed/                        # Database seeding
│   ├── schema.sql
│   └── generator.py
│
├── alembic/                     # DB migrations
├── docker-compose.yml
├── pyproject.toml
└── README.md
```

## Testing

Run the test suite:

```bash
# All tests
pytest tests/

# With coverage
pytest tests/ --cov=app

# Only agent tests
pytest tests/agent/test_graph.py -v

# Only safety tests (validator)
pytest tests/tools/test_validator.py -v
```

Expected results:
- **Validator**: 100% of unsafe queries blocked (DROP, DELETE, UPDATE, INSERT, system catalog)
- **Schema retrieval**: No hallucination (only returns requested tables)
- **Agent**: Happy path, error recovery, iteration budget respected

## Safety & Security

### Design Principles

1. **Deterministic safety layer**
   - Validator uses sqlglot AST parsing (not regex or string matching)
   - All destructive operations rejected before execution
   - Row limits and timeouts enforced at connection level

2. **Read-only enforcement**
   - Target DB user has SELECT-only role
   - Connections timeout after 5 seconds
   - Query execution limited to 10,000 rows

3. **No secrets in logs**
   - API keys, connection strings never logged
   - LLM traces scrubbed of sensitive data
   - User data anonymized in Langfuse

4. **Conversation privacy**
   - Each user has isolated conversation threads
   - Long-term memory scoped to user
   - Query log includes result summary, not raw data

### Validation Rules

The validator rejects:
- Multi-statement queries (`;` separator)
- Destructive operations: DROP, DELETE, UPDATE, INSERT
- System catalog access: pg_catalog, information_schema
- Dangerous functions: pg_sleep, pg_execute_external_text
- Missing tables/columns (against retrieved schema)
- Fan-out joins (detected via cardinality analysis)

## Observability

All traces sent to Langfuse:
- **Schema retrieval**: tables, latency
- **SQL generation**: prompt, completion, tokens
- **Validation**: passes/failures, reasons
- **Execution**: latency, row count, cost
- **Retries**: error message, fix attempt

Dashboard: https://langfuse.com

## Contributing

1. Create a feature branch: `git checkout -b feature/my-feature`
2. Make changes and test: `pytest tests/`
3. Ensure type hints: `mypy app/`
4. Run linter: `ruff check app/`
5. Push and open PR

## License

MIT

## Roadmap

- [ ] Multi-database federation (Snowflake, BigQuery)
- [ ] Natural language explanations (why this query, data anomalies)
- [ ] Fine-tuned LLM for SQL generation
- [ ] BI dashboarding integration
- [ ] Real-time query optimization

## Support

- **Issues**: GitHub Issues
- **Docs**: See `docs/` directory
- **Roadmap**: See PROJECT_PLAN.md
