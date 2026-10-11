# Requirements Document

## Introduction

**Feature:** Seed DB and Baseline Text-to-SQL (Step 1 of QueryPilot Build Order)

Step 1 of the QueryPilot build order establishes the foundation for text-to-SQL evaluation. This step involves setting up a target PostgreSQL database with a realistic e-commerce schema, populating it with deterministic synthetic data spanning 2024–2025, configuring security roles, and implementing a single-call baseline LLM integration to measure initial performance before building the full agentic system.

The baseline serves as a quantitative reference point ("before" number) against which later improvements (schema retrieval, validation, retry loops, memory) are measured. All synthetic data must be **deterministically seeded** to ensure reproducibility across runs and environments.

## Glossary

- **Target DB**: The read-only PostgreSQL database containing e-commerce analytics data that the agent queries. Separate from the App DB.
- **App DB**: The PostgreSQL database for QueryPilot's own metadata (conversations, query logs, evaluation runs). The agent never queries this.
- **Deterministic Seeding**: Use a fixed random seed (e.g., `seed=42`) so that repeated runs produce identical data.
- **Read-Only Role**: A PostgreSQL role with `SELECT` permission only on Target DB tables; prevents accidental or malicious writes.
- **Synthetic Data**: Algorithmically generated customer, product, order, and order_item records designed to be realistic without exposing real PII.
- **Baseline LLM**: A simple text-to-SQL function that accepts a full schema and question, calls an LLM (Bedrock, Anthropic, OpenAI), and returns SQL in one call (no retry, no validation, no execution).
- **Swappable Provider**: LLM client is configured via environment variables; switching providers requires only config change, no code modification.
- **Evaluation Dataset**: A JSONL file with 20 starter items; each item contains a natural-language question, gold SQL, expected tables, and category.

## Requirements

### Requirement 1: Target Database Schema Definition

**User Story:** As an evaluation engineer, I want a normalized e-commerce schema so that I can test text-to-SQL correctness against realistic relational data.

#### Acceptance Criteria

1. WHEN the Target DB is initialized, THE Schema_Creator SHALL create tables: `customers`, `products`, `orders`, `order_items`, and `reviews`.

2. THE Customers_Table SHALL have columns: `id` (primary key, serial), `name` (VARCHAR), `email` (UNIQUE VARCHAR), `state` (VARCHAR, e.g., "CA", "NY"), `region` (VARCHAR, e.g., "West", "Northeast"), and `created_at` (TIMESTAMP DEFAULT CURRENT_TIMESTAMP).

3. THE Products_Table SHALL have columns: `id` (primary key, serial), `name` (VARCHAR), `category` (VARCHAR, e.g., "Electronics", "Apparel"), `price` (DECIMAL(10,2)), `stock_quantity` (INT), and `created_at` (TIMESTAMP DEFAULT CURRENT_TIMESTAMP).

4. THE Orders_Table SHALL have columns: `id` (primary key, serial), `customer_id` (INT, foreign key to customers.id), `created_at` (TIMESTAMP for when order was placed, separate from order_date), `order_date` (DATE, the date the order was placed, for time-series queries), `status` (VARCHAR: one of 'paid', 'refunded', 'cancelled'), and `total_amount` (DECIMAL(10,2)).

5. THE Order_Items_Table SHALL have columns: `id` (primary key, serial), `order_id` (INT, foreign key to orders.id), `product_id` (INT, foreign key to products.id), `quantity` (INT, >= 1), `unit_price` (DECIMAL(10,2)), and `created_at` (TIMESTAMP DEFAULT CURRENT_TIMESTAMP).

6. THE Reviews_Table SHALL have columns: `id` (primary key, serial), `product_id` (INT, foreign key to products.id), `customer_id` (INT, foreign key to customers.id), `rating` (INT, 1–5), `comment` (TEXT), and `created_at` (TIMESTAMP DEFAULT CURRENT_TIMESTAMP).

7. WHEN the Schema_Creator creates foreign key constraints, THE Schema_Creator SHALL index `orders.customer_id`, `orders.order_date`, `order_items.order_id`, `order_items.product_id`, `reviews.product_id`, and `reviews.customer_id` for query performance.

8. WHERE column comments are added, THE Schema_Creator SHALL add comments to explain business meaning; e.g., `"total_amount is the gross total before discounts"`, `"status tracks order fulfillment state"`, `"created_at is system timestamp, order_date is transaction date"`.

9. THE Schema_Creator SHALL validate that all tables are created with correct types, constraints, and indexes by running a verification query that counts tables (should be 5), checks column counts per table, and confirms primary/foreign keys.

### Requirement 2: Deterministic Synthetic Data Generation

**User Story:** As an evaluation engineer, I want deterministically seeded synthetic data so that I can reproduce test runs and compare LLM performance across iterations.

#### Acceptance Criteria

1. WHEN the Data_Generator is invoked with a seed value (default: 42), THE Data_Generator SHALL generate exactly 500 customer records with deterministic, repeatable output.

2. THE Data_Generator SHALL populate customers with realistic names, unique emails, U.S. states (CA, NY, TX, etc.), and regions derived from state; `created_at` timestamps shall be in 2024.

3. WHEN the Data_Generator generates customers, THE Data_Generator SHALL ensure names are diverse and plausible (e.g., using a name list or synthetic name generator), and emails shall match a pattern like `{name}.{random_suffix}@example.com`.

4. THE Data_Generator SHALL generate exactly 5,000 order records distributed across 2024 and 2025: approximately 60% in 2024, 40% in 2025, mimicking growth.

5. WHEN the Data_Generator assigns orders to customers, THE Data_Generator SHALL use a realistic distribution where some customers have many orders (0–50 orders per customer) and most have few (Pareto-like), rather than uniform.

6. WHEN the Data_Generator generates order statuses, THE Data_Generator SHALL assign statuses ('paid', 'refunded', 'cancelled') with realistic proportions: ~85% paid, ~10% refunded, ~5% cancelled.

7. THE Data_Generator SHALL generate approximately 50 product records covering categories (Electronics, Apparel, Home, Books, Sports) with prices and stock quantities that are realistic.

8. WHEN the Data_Generator creates order_items, THE Data_Generator SHALL generate an average of 3–5 items per order, drawn from the product list, with quantities (1–10) and unit prices that match the product price (plus or minus 10% for discounts/bulk pricing).

9. THE Data_Generator SHALL generate approximately 1,000–1,500 review records randomly distributed across products and customers, with ratings (1–5 stars) and optional comments.

10. WHEN the Data_Generator completes, THE Data_Generator SHALL verify record counts match expectations (500 customers, ~5,000 orders, ~50 products, row counts per table logged) and ensure no referential integrity violations.

11. WHEN the Data_Generator is run with the same seed value a second time (e.g., in a different environment), THE Data_Generator SHALL produce identical row counts, identical column values (names, emails, amounts, dates), and identical foreign key references.

### Requirement 3: Read-Only Database Role and Security

**User Story:** As a security engineer, I want the Target DB to enforce read-only access so that the application cannot accidentally or maliciously modify production data.

#### Acceptance Criteria

1. WHEN the Role_Manager initializes the Target DB, THE Role_Manager SHALL create a PostgreSQL role named `querypilot_ro` with no login privileges (login disabled or credentials stored only in environment).

2. THE Role_Manager SHALL grant `SELECT` permission on all tables in the `public` schema to `querypilot_ro` using `GRANT SELECT ON ALL TABLES IN SCHEMA public TO querypilot_ro;`.

3. WHEN the Role_Manager creates future tables in the public schema of Target DB, THE Role_Manager SHALL ensure the `DEFAULT PRIVILEGES` grant SELECT to `querypilot_ro` so new tables are automatically readable: `ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO querypilot_ro;`.

4. THE Role_Manager SHALL revoke INSERT, UPDATE, DELETE, and TRUNCATE permissions from `querypilot_ro` on all tables to ensure the role has zero write capability: `REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON ALL TABLES IN SCHEMA public FROM querypilot_ro;`.

5. WHEN the Application connects to Target DB, THE Application SHALL use the `querypilot_ro` role for all query execution; connection strings shall NOT use a superuser or admin role.

6. WHEN the Application executes a query, THE Application SHALL set `SET TRANSACTION READ ONLY;` at the start of every connection session to prevent transaction-level writes.

7. THE Role_Manager SHALL verify the role configuration by attempting a read query (should succeed) and an insert/update/delete query (should fail with permission denied).

### Requirement 4: Docker Compose Setup

**User Story:** As a developer, I want a Docker Compose environment so that I can spin up Target DB, App DB, and supporting services with one command for local development.

#### Acceptance Criteria

1. WHEN a developer runs `docker-compose up -d`, THE Docker_Orchestrator SHALL start two PostgreSQL 16 services: `target_db` and `app_db`.

2. THE Docker_Orchestrator SHALL configure `target_db` service with:
   - Container name: `querypilot_target_db`
   - Port: 5433 (default, configurable via env var)
   - Default database: `querypilot_target`
   - Default user: `analytics_user` with password from `TARGET_DB_PASSWORD` env var
   - Initialization script: load `seed/schema.sql` and run `seed/generator.py` to populate data
   - Health check: `pg_isready -U analytics_user` every 5 seconds, timeout 10 seconds

3. THE Docker_Orchestrator SHALL configure `app_db` service with:
   - Container name: `querypilot_app_db`
   - Port: 5432 (default, configurable via env var)
   - Default database: `querypilot_app`
   - Default user: `app_user` with password from `APP_DB_PASSWORD` env var
   - Initialization script: load `seed/app_schema.sql` (creates conversations, query_log, eval_runs tables)
   - Health check: `pg_isready -U app_user` every 5 seconds, timeout 10 seconds

4. THE Docker_Orchestrator SHALL pass database connection URLs to the app container via environment variables: `TARGET_DB_URL`, `APP_DB_URL`, `TARGET_DB_READONLY_ROLE`.

5. WHERE environment variables are used, THE Docker_Orchestrator SHALL read them from a `.env` file (or `.env.override` for local dev); the `.env` file shall not be committed to version control.

6. WHEN `docker-compose up` completes, THE Docker_Orchestrator SHALL ensure both databases are healthy (health check passing) before reporting success; the output shall indicate both services are ready.

7. THE Docker_Orchestrator SHALL support `docker-compose down` to stop and remove containers, preserving no data (development environment only).

### Requirement 5: Baseline LLM Client Interface

**User Story:** As a developer, I want an abstract LLM client interface so that I can swap between OpenAI, Anthropic, and AWS Bedrock providers without changing the baseline evaluation logic.

#### Acceptance Criteria

1. WHEN the Baseline_Evaluator initializes, THE Baseline_Evaluator SHALL define an abstract `LLMClient` interface with a method `call(prompt: str, config: Config) -> str` that returns the LLM's response (SQL).

2. THE Baseline_Evaluator SHALL implement three concrete providers:
   - `OpenAIClient`: uses OpenAI API (model from config, e.g., `gpt-4-turbo`)
   - `AnthropicClient`: uses Anthropic API (model from config, e.g., `claude-3-opus`)
   - `BedrockClient`: uses AWS Bedrock (model ID from config, e.g., `anthropic.claude-3-sonnet`)

3. WHEN the Baseline_Evaluator loads configuration, THE Baseline_Evaluator SHALL read `LLM_PROVIDER` (one of "openai", "anthropic", "bedrock") and `LLM_MODEL` env vars to instantiate the correct provider.

4. WHEN the Baseline_Evaluator loads credentials, THE Baseline_Evaluator SHALL read provider-specific keys from env vars (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `AWS_ACCESS_KEY_ID` + `AWS_SECRET_ACCESS_KEY`) without hardcoding them in source code.

5. THE Baseline_Evaluator SHALL NOT log or expose API keys, credentials, or model responses containing sensitive data; errors shall be sanitized before logging.

6. WHERE the LLMClient is called, THE Baseline_Evaluator SHALL handle errors (rate limits, timeouts, invalid credentials) by raising a descriptive exception (e.g., `LLMError`) that includes the provider name and error category (API error, auth error, timeout).

7. THE Baseline_Evaluator SHALL support provider-specific parameters via the config (e.g., temperature, max_tokens) so that baseline behavior can be tuned without code changes.

8. THE Baseline_Evaluator SHALL verify the interface by successfully calling each provider (OpenAI, Anthropic, Bedrock) with a simple prompt and receiving a response; if a provider is not configured (env var missing), the test shall skip that provider gracefully.

### Requirement 6: Baseline Text-to-SQL Function

**User Story:** As an evaluation engineer, I want a single-call baseline that sends the full schema and question to the LLM, so that I can measure how well a naive prompt performs before adding validation and retry logic.

#### Acceptance Criteria

1. WHEN the Baseline_Evaluator is invoked with a natural-language question, THE Baseline_Evaluator SHALL construct a prompt that includes: the full Target DB schema (DDL, column types, foreign keys, table descriptions), the business context (order statuses mean this, "revenue" is defined as that), and the user's question.

2. WHEN the Baseline_Evaluator constructs the prompt, THE Baseline_Evaluator SHALL format the schema in a clear, parseable way (e.g., human-readable table descriptions followed by column metadata) to maximize LLM comprehension.

3. THE Baseline_Evaluator SHALL include instructions in the prompt such as: "Return ONLY valid PostgreSQL SQL. Do not include explanations, code blocks, or markdown. Do not use CREATE, INSERT, UPDATE, DELETE, or DROP statements. Use aliases for clarity."

4. WHEN the Baseline_Evaluator sends the prompt to the LLM, THE Baseline_Evaluator SHALL call the swappable LLMClient with the constructed prompt and receive the LLM's response.

5. WHEN the Baseline_Evaluator receives the LLM's response, THE Baseline_Evaluator SHALL extract the SQL by removing code block markers (e.g., ` ```sql ` and ` ``` `) if present; if the response contains no valid-looking SQL, the Baseline_Evaluator SHALL raise an error `InvalidResponseError`.

6. WHEN the Baseline_Evaluator extracts SQL, THE Baseline_Evaluator SHALL perform no validation (no sqlglot parse, no table allowlist check); this is the baseline, so all generated SQL is attempted as-is.

7. THE Baseline_Evaluator SHALL return the extracted SQL as a string; the caller (evaluation harness) is responsible for execution and result comparison.

8. WHERE the Baseline_Evaluator is called, THE Baseline_Evaluator SHALL log the question, the LLM provider, the LLM model, tokens used (if available), and the extracted SQL to the query_log table in App DB for durability and analysis.

### Requirement 7: Evaluation Dataset

**User Story:** As an evaluation engineer, I want a starter dataset of 20 gold queries so that I can measure baseline accuracy and track improvement as the agent develops.

#### Acceptance Criteria

1. WHEN the Evaluation_Dataset is created, THE Evaluation_Dataset SHALL contain exactly 20 items in JSONL format, one item per line.

2. EACH item in THE Evaluation_Dataset SHALL have the following fields:
   - `question` (string): a natural-language question asked by a business user
   - `gold_sql` (string): the canonical SQL that correctly answers the question
   - `expected_tables` (list of strings): the tables that must be referenced (e.g., `["orders", "order_items"]`)
   - `category` (string): one of `simple_aggregation`, `joins`, `time_comparison`, `ambiguous`

3. WHEN the Evaluation_Dataset is constructed, THE Evaluation_Dataset SHALL ensure categories are balanced: at least 5 items per category, with the following subcategory coverage:
   - **simple_aggregation (5)**: "How many customers?", "What is average order amount?", "Total revenue by category?", "Count of paid vs refunded orders?", "What is the most popular product?"
   - **joins (5)**: "Orders with customer names", "Top 5 customers by order count", "Products ordered by each customer", "Orders with review ratings", "Revenue by customer region"
   - **time_comparison (5)**: "Compare 2024 vs 2025 total orders", "YoY revenue comparison", "Month-over-month growth in orders", "Orders created in Q4 2024 vs Q4 2023 (none exist, edge case)", "Customer acquisition trend"
   - **ambiguous (5)**: "Revenue trend", "Top customers", "Best sellers", "Customer engagement", "Sale trends"

4. WHEN THE Evaluation_Dataset is created, EACH simple_aggregation item SHALL have SQL that uses only one or two tables and simple GROUP BY / aggregate functions (COUNT, SUM, AVG, MAX, MIN).

5. WHEN THE Evaluation_Dataset is created, EACH joins item SHALL have SQL that joins at least two tables via foreign keys or derived conditions.

6. WHEN THE Evaluation_Dataset is created, EACH time_comparison item SHALL include date filtering (WHERE order_date BETWEEN ...) or temporal aggregation (EXTRACT(YEAR/MONTH), GROUP BY YEAR, etc.); at least one item shall compare 2024 vs 2025.

7. WHEN THE Evaluation_Dataset is created, EACH ambiguous item SHALL be phrased in natural language that a domain expert could interpret multiple ways; the gold_sql shall represent one canonical interpretation (documented in a comment).

8. WHEN THE Evaluation_Dataset is constructed, THE Evaluation_Dataset SHALL ensure all gold_sql queries are syntactically valid PostgreSQL, executable against the Target DB schema (with seed data loaded), and return non-empty results (or documented as "no results expected" if testing an edge case like "Orders in year 2023").

9. WHEN THE Evaluation_Dataset is created, THE Evaluation_Dataset SHALL be stored in `eval/dataset.jsonl` with no trailing blank lines; it SHALL be version-controlled so baselines can be compared over time.

### Requirement 8: Baseline Evaluation Execution

**User Story:** As an evaluation engineer, I want to run the baseline against the 20-item dataset and record accuracy so that I have a quantitative "before" number for later comparison.

#### Acceptance Criteria

1. WHEN the Evaluation_Harness is invoked with `python -m eval.run_eval --baseline`, THE Evaluation_Harness SHALL load the 20 items from `eval/dataset.jsonl`.

2. FOR EACH item in THE Evaluation_Dataset, THE Evaluation_Harness SHALL:
   - Call the Baseline_LLM with the question
   - Capture the returned SQL
   - Execute the returned SQL against Target DB (using querypilot_ro role)
   - Execute the gold_sql against Target DB
   - Compare result sets (columns and rows, order-insensitive unless ORDER BY is present)
   - Record: question, category, gold_sql, generated_sql, result_match (true/false), error (if any)

3. WHEN the Evaluation_Harness executes SQL, THE Evaluation_Harness SHALL set a query timeout (5 seconds) and row fetch limit (1000 rows) to prevent runaway queries.

4. WHEN the Evaluation_Harness encounters a SQL error (syntax, runtime), THE Evaluation_Harness SHALL record error type (parse error, execution error, timeout) and message (sanitized, no internal stack traces visible in output).

5. WHEN the Evaluation_Harness encounters a result mismatch (columns differ, row counts differ, values differ), THE Evaluation_Harness SHALL record false and the mismatch reason (e.g., "expected 10 rows, got 5").

6. WHEN the Evaluation_Harness completes all 20 items, THE Evaluation_Harness SHALL compute and display:
   - Accuracy: (items with matching results) / 20
   - Category breakdown: accuracy per category (simple_aggregation %, joins %, etc.)
   - Error rate: (items with SQL errors) / 20
   - Coverage: (items that executed successfully, regardless of accuracy) / 20

7. THE Evaluation_Harness SHALL log the full evaluation run (all item results) to the `eval_runs` table in App DB with: run_id, run_timestamp, baseline_provider, baseline_model, overall_accuracy, category_breakdown (JSON), and full_results (JSON or JSONL).

8. WHEN the Evaluation_Harness completes, THE Evaluation_Harness SHALL print a summary to stdout in a human-readable format (e.g., table with categories and accuracies) and save a detailed JSON report to `eval/baseline_results.json`.

### Requirement 9: Configuration and Environment Variables

**User Story:** As a developer, I want all configuration to be environment-driven so that I can run the same code in dev, staging, and production by changing only env vars.

#### Acceptance Criteria

1. WHEN the Application starts, THE Configuration_Manager SHALL read from a `.env` file (or directly from environment variables if deployed without a file).

2. THE Configuration_Manager SHALL define the following variables (see `.env.example` for defaults and descriptions):
   - Database: `TARGET_DB_URL`, `APP_DB_URL`, `TARGET_DB_READONLY_ROLE`
   - LLM: `LLM_PROVIDER`, `LLM_MODEL`, provider-specific keys (`OPENAI_API_KEY`, etc.)
   - Query execution: `QUERY_TIMEOUT_SECONDS` (default: 5), `RESULT_ROW_LIMIT` (default: 1000)
   - Debug: `DEBUG` (default: false)

3. WHERE sensitive values (API keys, database passwords) are required, THE Configuration_Manager SHALL read them from environment variables only; it SHALL NOT have default values in code.

4. WHEN Configuration_Manager validates, THE Configuration_Manager SHALL raise an error if a required variable is missing; errors SHALL be descriptive (e.g., "Missing required env var: OPENAI_API_KEY").

5. THE Configuration_Manager SHALL use Pydantic `BaseSettings` and `pydantic-settings` for type-safe, validated config with sensible defaults for non-sensitive values.

6. WHERE the Configuration is used in logging, THE Configuration_Manager SHALL NEVER log sensitive values (passwords, API keys, auth tokens); it MAY log which provider/model is in use without credential details.

7. WHEN the `.env.example` file is created, THE Configuration_Manager SHALL include all required and optional variables with placeholder values and inline comments explaining each; `.env.example` SHALL be version-controlled.

### Requirement 10: Verification and Health Checks

**User Story:** As a developer, I want automated health checks so that I can verify the database is seeded correctly and the baseline LLM client is working before running evaluations.

#### Acceptance Criteria

1. WHEN the Verification_Suite is run with `python -m seed.verify`, THE Verification_Suite SHALL perform the following checks:
   - Target DB is reachable (ping with pg_isready)
   - querypilot_ro role exists and has SELECT permission
   - All 5 tables exist (customers, products, orders, order_items, reviews)
   - All tables have expected row counts (500 customers, 5000 orders, ~50 products, etc.)
   - All tables have expected columns with correct types
   - Foreign key constraints are present and valid (no orphaned rows)
   - Indexes on FK and date columns are present

2. WHEN the Verification_Suite is run with `python -m app.verify_llm`, THE Verification_Suite SHALL:
   - Check that LLM_PROVIDER is set and recognized
   - Attempt to instantiate the LLMClient for the configured provider
   - Send a simple test prompt (e.g., "SELECT 1;") to verify credentials are valid
   - Report success or error for each provider checked

3. WHEN a check fails, THE Verification_Suite SHALL print a descriptive error message with remediation steps (e.g., "Table customers has 400 rows, expected 500; re-run data generator").

4. WHEN all checks pass, THE Verification_Suite SHALL print "✓ All checks passed" and exit with code 0; if any check fails, it SHALL exit with code 1.

5. THE Verification_Suite SHALL be idempotent: running it multiple times produces the same results without side effects.

---

## Acceptance Criteria Summary

**Schema Correctness (Requirement 1):**
- 5 tables created with correct schema
- Foreign keys, indexes, and column types verified
- Column comments document business meaning

**Data Seeding (Requirement 2):**
- 500 customers, ~5,000 orders, ~50 products generated
- Deterministic seed ensures reproducibility
- Realistic distributions (Pareto customer orders, status ratios)
- Record counts and referential integrity validated

**Security (Requirement 3):**
- Read-only role created and permission-verified
- Zero write capability for querypilot_ro
- Connection enforces `SET TRANSACTION READ ONLY`

**Docker Setup (Requirement 4):**
- Two PostgreSQL services (target_db, app_db) start with one command
- Health checks ensure both are ready before proceeding
- Env vars configure connection details

**LLM Client (Requirement 5):**
- Swappable interface supports OpenAI, Anthropic, Bedrock
- Provider switching via config only (no code change)
- Error handling and credential security verified

**Baseline Function (Requirement 6):**
- Single-call baseline sends schema + question to LLM
- SQL extraction from response (markdown cleanup)
- No validation performed (baseline as-is)

**Dataset (Requirement 7):**
- 20 items covering simple_aggregation, joins, time_comparison, ambiguous
- All gold_sql queries are valid and executable
- Items stored in `eval/dataset.jsonl`

**Evaluation Execution (Requirement 8):**
- Baseline runs against all 20 items, comparing results to gold
- Accuracy computed and reported by category
- Full run logged to App DB

**Configuration (Requirement 9):**
- All config read from environment variables
- `.env.example` documents all vars
- Sensitive values never logged

**Verification (Requirement 10):**
- Automated health checks verify database schema and data
- LLM client connectivity verified
- Idempotent, descriptive failure messages
