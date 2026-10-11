# Tasks: Seed DB and Baseline Text-to-SQL

## Task Organization

Tasks are grouped by component and ordered to minimize dependencies. Each task is a single, atomic unit of work (~1–2 hours). Tasks include acceptance criteria (directly from requirements), dependencies, and estimated effort.

---

## Tier 1: Foundation (Schema & Configuration)

### Task 1.1: Create Target DB Schema (schema.sql)

**Description:** Define and create the target database schema with 5 tables, foreign keys, indexes, and role-based security.

**Acceptance Criteria:**
- WHEN schema.sql is executed, it creates 5 tables: customers, products, orders, order_items, reviews
- Each table has the correct columns with appropriate types (VARCHAR, INT, DECIMAL, DATE, TIMESTAMP)
- Foreign keys are defined with proper ON DELETE clauses (RESTRICT or CASCADE as appropriate)
- Indexes exist on: orders.customer_id, orders.order_date, order_items.order_id, order_items.product_id, reviews.product_id, reviews.customer_id
- Column comments describe business meaning (e.g., "total_amount is the gross total before discounts")
- querypilot_ro role is created with SELECT-only permissions
- DEFAULT PRIVILEGES are configured so new tables automatically grant SELECT to querypilot_ro
- WHEN `psql < seed/schema.sql` is executed, all objects are created without errors
- WHEN a verification query counts tables, it returns exactly 5; checks confirm all columns and indexes present

**Dependencies:** None

**Effort:** 45 min

---

### Task 1.2: Create App DB Schema (seed/app_schema.sql)

**Description:** Define the application metadata schema with conversations, query_log, and eval_runs tables.

**Acceptance Criteria:**
- WHEN app_schema.sql is executed, it creates conversations, query_log, eval_runs tables
- conversations table has columns: id (PK), user_id, title, created_at
- query_log table has columns: id (PK), timestamp, question, provider, model, generated_sql, tokens_used, metadata
- eval_runs table has columns: id (PK), run_timestamp, baseline_provider, baseline_model, overall_accuracy, category_breakdown (JSON), full_results (JSON)
- All tables have appropriate types and constraints
- WHEN `psql < seed/app_schema.sql` is executed, all objects are created without errors
- WHEN a verification query counts tables, it returns exactly 3 with expected columns

**Dependencies:** None

**Effort:** 30 min

---

### Task 1.3: Implement Config (app/config.py) with Pydantic BaseSettings

**Description:** Create centralized configuration management using pydantic-settings that reads from environment variables and .env file.

**Acceptance Criteria:**
- Config class inherits from pydantic_settings.BaseSettings
- Reads from .env file using pydantic-settings
- Required fields are defined: target_db_url, app_db_url, llm_provider, llm_model
- Optional fields with sensible defaults: query_timeout_seconds (5), result_row_limit (1000), llm_temperature (0.0), llm_max_tokens (2048), debug (False)
- Provider-specific optional fields: openai_api_key, anthropic_api_key, aws_access_key_id, aws_secret_access_key, aws_region
- validate_required_vars() method checks all required vars and raises descriptive ValueError if missing
- Sensitive values (API keys, passwords) are never logged or exposed in __repr__()
- WHEN `from app.config import Config; Config()` is executed, it loads .env successfully and validates without errors
- WHEN a required var is missing, a descriptive error is raised: "Missing required env var: ..."

**Dependencies:** None

**Effort:** 30 min

---

### Task 1.4: Create .env.example Documentation

**Description:** Document all environment variables with placeholder values and inline comments for developer reference.

**Acceptance Criteria:**
- .env.example documents all required and optional env vars
- Includes inline comments explaining each variable's purpose (e.g., "# Database URL for Target DB (read-only analytics data)")
- Organized by section: Database, Query Execution, LLM, Debug
- Provides examples for each LLM provider (openai, anthropic, bedrock)
- Placeholder values are clearly marked (e.g., "sk-..." for API keys, "postgresql://..." for URLs)
- File is human-readable and all vars are self-documenting
- WHEN developers copy .env.example to .env and fill in values, all required config is available

**Dependencies:** None

**Effort:** 15 min

---

## Tier 2: Data Generation

### Task 2.1: Implement DataGenerator Class (seed/generator.py)

**Description:** Build the deterministic synthetic data generator with methods for each entity type.

**Acceptance Criteria:**
- DataGenerator class accepts seed parameter (default: 42) for reproducibility
- Methods: generate_customers(count), generate_products(count), generate_orders(count, num_customers), generate_order_items(orders, num_products), generate_reviews(count, num_customers, num_products)
- All methods return generators (yield dict for each record, not lists)
- Deterministic: running with the same seed produces identical output
- generate_customers(500): produces 500 unique records with diverse names, emails, U.S. states (CA, NY, TX, etc.), regions derived from state, all created_at in 2024
- generate_products(50): produces 50 records with categories (Electronics, Apparel, Home, Books, Sports), realistic prices (10–500 USD), stock quantities
- generate_orders(5000, 500): produces 5000 orders with Pareto distribution (some customers many orders, most few), ~60% in 2024, ~40% in 2025, status ratios 85% paid / 10% refunded / 5% cancelled
- generate_order_items(orders, 50): produces 3–5 items per order, random products, quantities 1–10, unit_prices matching product prices
- generate_reviews(1250, 500, 50): produces ~1250 reviews with 1–5 ratings, optional comments
- WHEN run with seed=42 twice in a row, outputs are bit-for-bit identical (row counts, column values, FK references)

**Dependencies:** None

**Effort:** 90 min

---

### Task 2.2: Implement populate_database() Method

**Description:** Connect to target database and batch-insert all generated data.

**Acceptance Criteria:**
- populate_database() connects to target_db_url from config
- Inserts generated data in batches: customers, products, orders, order_items, reviews
- Each batch is committed separately to database
- Logs row counts after each batch (for verification): "Inserted 500 customers", "Inserted 50 products", etc.
- AFTER populate_database() completes, verify row counts match expected: 500 customers, ~5000 orders, 50 products, ~20000 order_items, ~1250 reviews
- Foreign key constraints are satisfied (no orphaned rows)

**Dependencies:** Task 2.1, Task 1.3 (config)

**Effort:** 45 min

---

### Task 2.3: Implement seed/verify.py Verification Script

**Description:** Create automated verification checks for database schema, data, and role configuration.

**Acceptance Criteria:**
- verify_schema(config): checks that all 5 tables exist, row counts match expected (500 customers, ~5000 orders), foreign key constraints are present and valid (no orphaned rows), indexes on FK and date columns are present
- verify_role(config): checks that querypilot_ro role exists, SELECT succeeds when connected as querypilot_ro, INSERT fails with permission error
- main(): runs all checks, prints "✓ <check_name> passed" or "✗ <check_name> failed: <reason>" for each check
- Exit code 0 if all checks pass, 1 if any check fails
- WHEN `python -m seed.verify` is run after data seeding, all checks should pass
- WHEN run before data seeding, appropriate checks fail with remediation steps

**Dependencies:** Task 1.1, Task 1.3, Task 2.2

**Effort:** 45 min

---

## Tier 3: Docker Setup

### Task 3.1: Create docker-compose.yml with Two PostgreSQL Services

**Description:** Define Docker Compose configuration to orchestrate target_db and app_db services with initialization and health checks.

**Acceptance Criteria:**
- target_db service is configured with:
  - postgres:16-alpine image
  - Container name: querypilot_target_db
  - Port: 5433 (configurable via TARGET_DB_PORT env var)
  - Database: querypilot_target
  - User: analytics_user with password from TARGET_DB_PASSWORD env var
  - Init scripts: loads seed/schema.sql and runs seed/generator.py to populate data
  - Health check: pg_isready every 5s, timeout 10s, 5 retries, start_period 10s
  - Volume: target_db_data persists across container restarts
- app_db service is configured with:
  - postgres:16-alpine image
  - Container name: querypilot_app_db
  - Port: 5432 (configurable via APP_DB_PORT env var)
  - Database: querypilot_app
  - User: app_user with password from APP_DB_PASSWORD env var
  - Init scripts: loads seed/app_schema.sql
  - Health check: pg_isready every 5s, timeout 10s, 5 retries, start_period 10s
  - Volume: app_db_data persists across container restarts
- Both services connected via querypilot_net bridge network
- WHEN `docker-compose up -d` is run, both services start, health checks pass within 30 seconds, databases are initialized
- WHEN `docker-compose down` is run, containers are stopped and removed (volumes persist for dev)
- Connection URLs are available via environment variables: TARGET_DB_URL, APP_DB_URL

**Dependencies:** Task 1.1, Task 1.2, Task 2.2

**Effort:** 45 min

---

### Task 3.2: Create Dockerfile for FastAPI App (bonus, if needed for context)

**Description:** Define multi-stage Docker build for the QueryPilot application.

**Acceptance Criteria:**
- Multi-stage Dockerfile with dependencies stage and runtime stage
- Base image: python:3.11-slim
- Copies pyproject.toml and installs dependencies via uv
- Non-root user: querypilot (UID 1000)
- Health check: `curl -f http://localhost:8000/health` every 30s
- Entry point: `python -m uvicorn app.main:app --host 0.0.0.0 --port 8000`
- WHEN `docker build -t querypilot:latest .` is run, build completes successfully
- WHEN `docker run querypilot:latest` is run, health check passes

**Dependencies:** Task 1.3 (config)

**Effort:** 30 min

---

## Tier 4: LLM Client Interface

### Task 4.1: Define LLMClient Abstract Interface and LLMError Exception

**Description:** Define the abstract interface and error types for LLM provider integration.

**Acceptance Criteria:**
- LLMError exception has fields: provider (str), error_category (str: "auth_error", "rate_limit", "timeout", "api_error"), message (str)
- LLMError.__repr__() shows provider and error_category, but never exposes credentials
- Abstract class LLMClient has abstract method: call(prompt: str) -> str
- LLMClient subclasses implement the call() method for their provider
- Verification: Can instantiate LLMClient subclasses and catch LLMError exceptions without errors

**Dependencies:** None

**Effort:** 20 min

---

### Task 4.2: Implement OpenAIClient

**Description:** Implement OpenAI API integration for text-to-SQL baseline.

**Acceptance Criteria:**
- OpenAIClient inherits from LLMClient
- Constructor: api_key, model (default: gpt-4-turbo), temperature, max_tokens
- call(prompt) sends request to OpenAI API using openai library, returns response text
- Error handling:
  - AuthenticationError → raises LLMError(provider="openai", error_category="auth_error")
  - RateLimitError → raises LLMError(provider="openai", error_category="rate_limit")
  - Timeout → raises LLMError(provider="openai", error_category="timeout")
  - Generic Exception → raises LLMError(provider="openai", error_category="api_error")
- Verification:
  - WITH valid OPENAI_API_KEY, call("SELECT 1;") returns a response
  - WITH invalid key, raises LLMError with error_category="auth_error"

**Dependencies:** Task 4.1

**Effort:** 30 min

---

### Task 4.3: Implement AnthropicClient

**Description:** Implement Anthropic API integration for text-to-SQL baseline.

**Acceptance Criteria:**
- AnthropicClient inherits from LLMClient
- Constructor: api_key, model (default: claude-3-opus-20240229), temperature, max_tokens
- call(prompt) sends request to Anthropic API using anthropic library, returns response text
- Error handling: catches AuthenticationError, RateLimitError, APITimeout → raises LLMError with appropriate error_category
- Verification:
  - WITH valid ANTHROPIC_API_KEY, call("SELECT 1;") returns a response
  - WITH invalid key, raises LLMError with error_category="auth_error"

**Dependencies:** Task 4.1

**Effort:** 30 min

---

### Task 4.4: Implement BedrockClient

**Description:** Implement AWS Bedrock API integration for text-to-SQL baseline.

**Acceptance Criteria:**
- BedrockClient inherits from LLMClient
- Constructor: model (default: anthropic.claude-3-sonnet-...), region (default: us-east-1), temperature, max_tokens
- call(prompt) uses boto3 to invoke Bedrock model, parses response JSON, extracts and returns text
- Error handling: catches all exceptions as LLMError(provider="bedrock", error_category="api_error")
- Uses AWS credentials from environment (AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY)
- Verification:
  - WITH valid AWS credentials, call("SELECT 1;") returns a response
  - WITH invalid credentials, raises LLMError with error_category="api_error"

**Dependencies:** Task 4.1

**Effort:** 40 min

---

### Task 4.5: Implement get_llm_client Factory Function

**Description:** Create factory function to instantiate the correct LLM client based on configuration.

**Acceptance Criteria:**
- Function: get_llm_client(config) -> LLMClient
- Reads config.llm_provider and config.llm_model
- IF provider == "openai": instantiates and returns OpenAIClient(config.openai_api_key, config.llm_model, ...)
- IF provider == "anthropic": instantiates and returns AnthropicClient(config.anthropic_api_key, config.llm_model, ...)
- IF provider == "bedrock": instantiates and returns BedrockClient(config.llm_model, ...)
- IF provider not recognized or required credentials missing, raises ConfigError with descriptive message
- Verification: get_llm_client(config) with LLM_PROVIDER=openai returns OpenAIClient instance; with invalid provider raises ConfigError

**Dependencies:** Task 4.2, Task 4.3, Task 4.4, Task 1.3

**Effort:** 20 min

---

### Task 4.6: Implement app/verify_llm.py Verification Script

**Description:** Create script to verify LLM client connectivity and configuration.

**Acceptance Criteria:**
- Loads configuration from .env
- Instantiates LLM client via get_llm_client(config)
- Calls client.call("Write the SQL: SELECT 1;") to verify connectivity
- ON success, prints: "✓ Provider: <provider>, Model: <model>, Response length: <N>"
- ON failure, prints: "✗ Error: <error_category>: <message>"
- Exit code 0 if successful, 1 if error
- Verification: `python -m app.verify_llm` runs to completion with LLM_PROVIDER=openai (or another configured provider)

**Dependencies:** Task 4.5, Task 1.3

**Effort:** 20 min

---

## Tier 5: Baseline Text-to-SQL Function

### Task 5.1: Implement construct_prompt() and extract_sql() Helper Functions

**Description:** Create utility functions for prompt construction and SQL extraction from LLM responses.

**Acceptance Criteria:**
- construct_prompt(question: str, schema_context: str) -> str
  - Returns a prompt string that includes:
    - The full schema description (table names, columns, types, foreign keys, descriptions)
    - Explicit instructions: "Return ONLY valid PostgreSQL SQL. Do not use CREATE/INSERT/UPDATE/DELETE/DROP. Use aliases for clarity."
    - The business context (what status values mean, what "revenue" is, etc.)
    - The natural-language question
  - Prompt is formatted clearly to maximize LLM comprehension
- extract_sql(response: str) -> str
  - Removes markdown code block markers (```sql ... ```)
  - Handles responses without code blocks, multiple code blocks (takes first), leading/trailing whitespace
  - Returns clean SQL string
  - Returns empty string if no SQL-like content found
- Verification:
  - construct_prompt("How many customers?", schema) produces a valid prompt containing the question and schema
  - extract_sql("```sql\nSELECT 1;\n```") returns "SELECT 1"
  - extract_sql("SELECT 1;") returns "SELECT 1"
  - extract_sql("Here is the query: ```sql\nSELECT * FROM orders\n```") returns "SELECT * FROM orders"

**Dependencies:** None

**Effort:** 20 min

---

### Task 5.2: Implement baseline_text_to_sql() Function

**Description:** Create the baseline single-call text-to-SQL function that sends schema + question to LLM.

**Acceptance Criteria:**
- Function signature: baseline_text_to_sql(question: str, schema_context: str, config: Config, llm_client: LLMClient) -> str
- Calls construct_prompt(question, schema_context) to build the prompt
- Calls llm_client.call(prompt), catches LLMError and re-raises
- Extracts SQL via extract_sql(response)
- IF extracted SQL is empty, raises InvalidResponseError with message "LLM returned no valid SQL"
- Returns extracted SQL string as-is (no validation, no allowlist check)
- Logs the question, provider, model, extracted SQL for later retrieval
- Verification:
  - WITH a mock LLM that returns "SELECT 1;", baseline_text_to_sql() returns "SELECT 1"
  - WITH a mock LLM that returns "I don't know.", baseline_text_to_sql() raises InvalidResponseError

**Dependencies:** Task 5.1, Task 4.1

**Effort:** 20 min

---

### Task 5.3: Implement Schema Fetching Tool (fetch_schema_from_target_db)

**Description:** Retrieve and format the target database schema for inclusion in prompts.

**Acceptance Criteria:**
- Function: fetch_schema_from_target_db(config) -> str
- Queries information_schema to retrieve table names, column names, types, foreign keys, descriptions
- Returns human-readable schema description (NOT raw SQL)
- Format example:
  ```
  TABLES:
  - customers (id, name, email, state, region, created_at) [500 rows]
    Columns: id INT, name VARCHAR(255), email VARCHAR(255) UNIQUE, ...
    Foreign Keys: none
    Indexes: idx_customers_email
  - orders (id, customer_id, created_at, order_date, status, total_amount) [~5000 rows]
    ...
  ```
- Includes column types, NOT NULL constraints, foreign key references, and descriptions
- Verification: Returns valid schema string with all 5 tables and expected columns

**Dependencies:** Task 1.3

**Effort:** 30 min

---

### Task 5.4: Implement SQL Execution Tool (execute_sql)

**Description:** Execute SQL queries against the target database with safety guardrails.

**Acceptance Criteria:**
- Function: execute_sql(sql: str, config: Config, timeout: int = 5) -> list[dict]
- Executes SQL against target_db_url using querypilot_ro role
- Sets `SET TRANSACTION READ ONLY;` before executing query
- Sets statement_timeout to enforce query timeout (prevents runaway queries)
- Fetches results up to result_row_limit, returns as list of dicts (columns as keys)
- ON syntax error: raises ExecutionError("SQL syntax error: <sanitized_message>")
- ON timeout: raises ExecutionError("Query timeout after <timeout>s")
- ON runtime error: raises ExecutionError("<error_type>: <sanitized_message>")
- ON permission error: raises ExecutionError("Permission denied (read-only role)")
- Verification:
  - execute_sql("SELECT COUNT(*) FROM customers;", config) returns [{'count': 500}]
  - execute_sql("SELECT * FROM customers LIMIT 5;", config) returns 5 rows as dicts
  - execute_sql("INSERT INTO customers (name, email, state) VALUES (...)", config) raises ExecutionError with "Permission denied"

**Dependencies:** Task 1.1, Task 1.3

**Effort:** 30 min

---

### Task 5.5: Implement Result Set Comparison (compare_result_sets)

**Description:** Compare two result sets (generated SQL vs. gold SQL) for equivalence.

**Acceptance Criteria:**
- Function: compare_result_sets(generated: list[dict], gold: list[dict], order_sensitive: bool = False) -> bool
- Checks row count match (if different, returns False)
- Checks column names match (keys in dicts; if different, returns False)
- Order-insensitive comparison: converts rows to sets of tuples, compares sets (unless order_sensitive=True)
- Handles NULL values correctly (NULL == NULL in comparison)
- Returns True if equivalent, False otherwise
- Verification:
  - compare_result_sets([{'id': 1}], [{'id': 1}]) returns True
  - compare_result_sets([{'id': 1}], [{'id': 2}]) returns False
  - compare_result_sets([{'id': 1, 'name': 'Alice'}], [{'id': 1, 'name': 'Alice'}]) returns True
  - compare_result_sets([{'id': 1}, {'id': 2}], [{'id': 2}, {'id': 1}]) returns True (order-insensitive)
  - compare_result_sets([{'id': 1, 'val': None}], [{'id': 1, 'val': None}]) returns True

**Dependencies:** None

**Effort:** 25 min

---

## Tier 6: Evaluation Dataset

### Task 6.1: Create eval/dataset.jsonl with 20 Starter Items

**Description:** Create a balanced evaluation dataset with 20 gold queries covering multiple categories.

**Acceptance Criteria:**
- File: eval/dataset.jsonl (JSONL format, one JSON object per line)
- Exactly 20 items, each with fields: question (str), gold_sql (str), expected_tables (list), category (str)
- Categories balanced with 5 items per category:
  - **simple_aggregation (5):** "How many customers?", "What is average order amount?", "Total revenue by category?", "Count of paid vs refunded orders?", "What is the most popular product?"
  - **joins (5):** "Orders with customer names", "Top 5 customers by order count", "Products ordered by each customer", "Orders with review ratings", "Revenue by customer region"
  - **time_comparison (5):** "Compare 2024 vs 2025 total orders", "YoY revenue comparison", "Month-over-month growth in orders", "Orders created in Q4 2024 vs Q4 2023", "Customer acquisition trend"
  - **ambiguous (5):** "Revenue trend", "Top customers", "Best sellers", "Customer engagement", "Sale trends"
- All gold_sql queries are syntactically valid PostgreSQL
- All queries execute successfully against target DB schema with seed data loaded
- Each query returns non-empty results (or explicitly documented as "edge case: no results expected")
- expected_tables lists the minimum tables required (e.g., ["customers", "orders"])
- WHEN `python -c "import json; [json.loads(line) for line in open('eval/dataset.jsonl')]"` is executed, all 20 items parse successfully
- File has no trailing blank lines

**Dependencies:** Task 1.1 (schema)

**Effort:** 90 min

---

## Tier 7: Evaluation Harness

### Task 7.1: Implement eval/run_eval.py Main Evaluation Runner

**Description:** Create the main evaluation harness that runs baseline against the dataset and records metrics.

**Acceptance Criteria:**
- Loads configuration from .env
- Loads 20 items from eval/dataset.jsonl
- Instantiates LLM client via get_llm_client(config)
- Fetches target DB schema once via fetch_schema_from_target_db(config)
- FOR each item in dataset:
  - Extract question
  - Call baseline_text_to_sql(question, schema, config, llm_client)
  - Execute generated SQL via execute_sql()
  - Execute gold SQL via execute_sql()
  - Compare results via compare_result_sets()
  - Record outcome: question, category, gold_sql, generated_sql, result_match (true/false), error (if any)
- Computes metrics:
  - overall_accuracy: (items with result_match=true) / 20
  - category_breakdown: accuracy per category (dict: {category: accuracy})
  - error_rate: (items with errors) / 20
  - error_breakdown: dict of error types and counts (e.g., {"permission_error": 1, "timeout": 2})
- Logs full run to App DB eval_runs table: run_id, run_timestamp, baseline_provider, baseline_model, overall_accuracy, category_breakdown (JSON), full_results (JSON)
- Prints summary to stdout in table format (e.g., markdown table with categories and accuracies)
- Saves detailed JSON report to eval/baseline_results.json
- Verification: `python -m eval.run_eval --baseline` runs to completion, prints summary, saves JSON report

**Dependencies:** Task 5.2, Task 5.3, Task 5.4, Task 5.5, Task 6.1, Task 1.3, Task 4.5

**Effort:** 90 min

---

### Task 7.2: Implement eval/metrics.py Helper Functions

**Description:** Create utility functions for metric computation and error sanitization.

**Acceptance Criteria:**
- compute_metrics(results: list[dict]) -> dict
  - Input: list of result dicts with keys: result_match (bool), category (str), error (str or None)
  - Returns dict with keys:
    - overall_accuracy: (true_matches / total)
    - coverage: (no_error_items / total)
    - error_rate: (error_items / total)
    - category_breakdown: {category: accuracy}
    - error_breakdown: {error_type: count}
  - Handles edge case: division by zero (empty results) returns 0 for all metrics
- sanitize_error(error_msg: str) -> str
  - Removes sensitive information: database URLs with passwords, API keys, connection strings
  - Example: "psycopg.OperationalError: connection to 'postgresql://user:pass@localhost/db' failed" → "psycopg.OperationalError: connection failed"
  - Returns sanitized message safe for logging
- Verification:
  - compute_metrics([{'result_match': True}, {'result_match': False}]) returns {'overall_accuracy': 0.5, ...}
  - sanitize_error("postgresql://user:secretpass@host/db") returns "postgresql://user:**@host/db" or similar

**Dependencies:** None

**Effort:** 30 min

---

### Task 7.3: Implement Query Logging to App DB

**Description:** Create functions to log queries and evaluation runs to the application database.

**Acceptance Criteria:**
- log_query(question: str, provider: str, model: str, generated_sql: str, tokens_used: int, metadata: dict, config: Config)
  - INSERT into query_log table: timestamp (NOW), question, provider, model, generated_sql, tokens_used, metadata (JSON)
  - Uses connection to app_db_url from config
- log_eval_run(run_timestamp: datetime, baseline_provider: str, baseline_model: str, overall_accuracy: float, category_breakdown: dict, full_results: dict or list, config: Config)
  - INSERT into eval_runs table: run_timestamp, baseline_provider, baseline_model, overall_accuracy, category_breakdown (JSON), full_results (JSON or JSONL)
  - Uses connection to app_db_url from config
- Both functions:
  - Never log sensitive data: no credentials, no full database URLs with passwords
  - Handle connection errors gracefully (log and continue, do not crash evaluation)
- Verification:
  - After run_eval completes, query_log has 20+ rows (one per item)
  - After run_eval completes, eval_runs has 1 row with run metrics
  - Logged data does not contain secrets

**Dependencies:** Task 1.2, Task 1.3

**Effort:** 30 min

---

## Tier 8: Integration & Verification

### Task 8.1: Full Integration Test (smoke test)

**Description:** Verify the entire pipeline works end-to-end with all components.

**Acceptance Criteria:**
- WHEN `docker-compose up -d` is run:
  - Both target_db and app_db services start successfully
  - Health checks pass within 30 seconds
  - Both databases are reachable
- WHEN `python -m seed.verify` is run:
  - All checks pass: schema exists, 5 tables present, data counts correct, FK integrity valid, indexes present
  - Exit code 0
- WHEN `python -m app.verify_llm` is run:
  - LLM client instantiates successfully (for configured provider)
  - Test call to LLM succeeds
  - Exit code 0
- WHEN `python -m eval.run_eval --baseline` is run:
  - Loads all 20 items from eval/dataset.jsonl
  - For each item, generates SQL, executes, compares results
  - Completes without critical errors
  - baseline_results.json is generated with valid metrics (overall_accuracy > 0%)
  - Prints summary to stdout
  - Query log in app_db contains 20+ entries
  - eval_runs in app_db contains 1 entry
- Full pipeline execution time: < 5 minutes (varies with LLM latency)
- Verification: Following all manual steps produces "✓ All checks passed" and baseline_results.json with accuracy metric

**Dependencies:** All prior tasks

**Effort:** 60 min (manual testing + troubleshooting)

---

### Task 8.2: Update pyproject.toml with Dependencies

**Description:** Add all required runtime and development dependencies with pinned versions.

**Acceptance Criteria:**
- Runtime dependencies:
  - psycopg (3.x): PostgreSQL async driver
  - pydantic (v2): data validation
  - pydantic-settings: environment configuration
  - sqlglot: SQL parsing (for later validation, not used in baseline)
  - fastapi: REST API framework
  - uvicorn: ASGI server
  - openai: OpenAI API client
  - anthropic: Anthropic API client
  - boto3: AWS Bedrock client
  - langfuse: observability (optional for baseline, added for completeness)
- Development dependencies:
  - pytest: testing framework
  - pytest-asyncio: async test support
  - pytest-cov: coverage reporting
  - black: code formatter
  - ruff: linter
  - mypy: type checker
- Versions are pinned exactly or conservatively (no wildcards for runtime):
  - Example: `fastapi==0.104.1` or `sqlglot>=23,<24`
- WHEN `uv sync` is run, all dependencies install without errors
- WHEN `pytest` is run, tests discover and execute
- WHEN `black --check app/` is run, formatting is valid
- WHEN `ruff check app/` is run, linting passes (configure to skip certain rules if needed)

**Dependencies:** None (final integration task)

**Effort:** 30 min

---

## Summary by Component

| Component | Tasks | Effort | Dependencies |
|---|---|---|---|
| Schema & Config | 1.1–1.4 | 2h | None |
| Data Generation | 2.1–2.3 | 3h | Schema, Config |
| Docker | 3.1–3.2 | 1.25h | Schema, Generator |
| LLM Client | 4.1–4.6 | 2.5h | Config |
| Baseline Function | 5.1–5.5 | 2h | LLM Client |
| Evaluation Dataset | 6.1 | 1.5h | Schema |
| Evaluation Harness | 7.1–7.3 | 2.5h | All prior |
| Integration | 8.1–8.2 | 1.5h | All prior |
| **Total** | **24 tasks** | **~16.75 hours** | **Sequential builds on tiers** |

---

## Recommended Implementation Order

To minimize blocking and enable parallel work:

1. **Tier 1 (Foundation):** 1.1, 1.2, 1.3, 1.4 (2h) — no dependencies, required by all later tasks
2. **Parallel tracks after Tier 1:**
   - **Track A (Data):** 2.1, 2.2, 2.3 (3h) → enables Docker setup
   - **Track B (LLM):** 4.1–4.6 (2.5h) → enables Baseline functions
   - **Track C (Dataset):** 6.1 (1.5h) → needs only schema
3. **Tier 3 (Docker):** 3.1, 3.2 (1.25h) — depends on Track A
4. **Tier 5 (Baseline):** 5.1–5.5 (2h) — depends on Track B
5. **Tier 7 (Harness):** 7.1–7.3 (2.5h) — depends on Tracks A, B, C
6. **Tier 8 (Integration):** 8.1, 8.2 (1.5h) — final verification and cleanup

**Parallel execution potential:**
- After Tier 1 complete, Tracks A, B, C can run in parallel
- Tier 3 must wait for Track A, but Tier 5 can proceed independently after Track B
- Tier 7 is the final integration point

---

## Verification Checklist (for review)

- [ ] All 5 tables in Target DB exist with correct schema and column comments
- [ ] querypilot_ro role exists with SELECT-only permissions
- [ ] 500 customers, ~5000 orders, ~50 products seeded deterministically
- [ ] docker-compose up -d starts both databases with passing health checks
- [ ] LLM client swaps between OpenAI, Anthropic, Bedrock via config
- [ ] Baseline function sends schema + question to LLM and extracts SQL
- [ ] 20 evaluation items in eval/dataset.jsonl cover all 4 categories
- [ ] run_eval --baseline completes and produces baseline_results.json with accuracy
- [ ] Query logs appear in App DB after evaluation
- [ ] All tests pass (seed.verify, app.verify_llm, run_eval)
- [ ] Dependencies in pyproject.toml are pinned and install without errors

