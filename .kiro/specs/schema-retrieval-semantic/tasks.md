# Tasks: Schema Retrieval and Semantic Layer

## Task Organization

Tasks are grouped by component and ordered to minimize dependencies. Each task is a single, atomic unit of work (~30–90 min). Tasks include acceptance criteria, dependencies, and estimated effort. The build is organized in 6 tiers, totaling ~16 tasks and ~14 hours of work.

---

## Tier A: Core Schema Introspection

### Task A.1: Implement get_schema_from_db() and Information Schema Queries

**Description:** Implement schema introspection by querying PostgreSQL information_schema to extract table names, columns, types, constraints, and metadata.

**Acceptance Criteria:**
- Function: `async get_schema_from_db(target_db_url: str) -> dict[str, Any]`
- Queries: `information_schema.tables`, `information_schema.columns`, `information_schema.key_column_usage`, `pg_description`, `pg_stat_user_tables`
- Returns dict with structure: `{table_name: {columns: [...], pk_columns: [...], row_count: int, description: str, fk_relationships: [], sampled_values: {}, ...}}`
- For each column, includes: name, type, nullable, default value, is_pk flag
- For each table, includes: row count (from pg_stat_user_tables), description (from pg_description), indexes (from pg_indexes)
- WHEN called, `get_schema_from_db()` queries all public schema tables exactly once per call (no redundant queries)
- WHEN an error occurs (DB connection, permission), raises SchemaError with message (never exposes raw DB error)
- Verification:
  - Call with target_db_url from config; returns dict with 5 tables (customers, products, orders, order_items, reviews)
  - customers table has columns: id (INT, PK), name, email, state, region, created_at
  - orders table has FK: customer_id → customers.id
  - Row counts match seed data (~500 customers, ~5000 orders)

**Dependencies:** None (uses seed DB from Step 1)

**Effort:** 75 min

---

### Task A.2: Implement get_table_metadata() and Sample Value Extraction

**Description:** Extract detailed metadata for a single table, including sample values for low-cardinality columns (< 20 distinct values).

**Acceptance Criteria:**
- Function: `async get_table_metadata(target_db_url: str, table_name: str) -> dict`
- Extracts: columns (with all types/constraints), PK columns, row count, description, indexes, FK relationships referencing or from this table
- Sample values: FOR columns with distinct count < 20, query `SELECT DISTINCT column_name LIMIT 20` and store as list
- Sample queries execute only if column is expected to be low-cardinality (hint from type or name)
- Handles edge cases: missing table → SchemaError, missing metadata → default to None, missing samples → empty dict
- WHEN called for table "orders", returns: columns list with id/customer_id/order_date/status/total_amount, row_count ~5000, FKs to/from this table
- WHEN called for column status (VARCHAR with 3 values), sampled_values['status'] = ['paid', 'refunded', 'cancelled']
- Verification:
  - get_table_metadata(..., "customers") returns metadata with 500 row_count, sampled_values for state and region columns
  - get_table_metadata(..., "invalid_table") raises SchemaError

**Dependencies:** Task A.1

**Effort:** 60 min

---

### Task A.3: Implement get_fk_relationships() for FK Extraction

**Description:** Extract all foreign key relationships from information_schema and return as structured list.

**Acceptance Criteria:**
- Function: `async get_fk_relationships(target_db_url: str) -> list[dict]`
- Returns list of dicts: `[{parent_table, parent_column, child_table, child_column, constraint_name}, ...]`
- Queries `information_schema.table_constraints` and `information_schema.key_column_usage`
- FOR each FK constraint, identifies: parent table, parent column, child table, child column
- Orders results by parent_table, then child_table for consistency
- WHEN called, returns all FKs in public schema (no duplicates)
- WHEN error occurs (permission, syntax), raises SchemaError
- Verification:
  - Returns dict with FK: {parent_table: 'customers', parent_column: 'id', child_table: 'orders', child_column: 'customer_id', ...}
  - Returns dict with FK: {parent_table: 'orders', parent_column: 'id', child_table: 'order_items', child_column: 'order_id', ...}
  - Total FK count matches seed schema (e.g., 5 FKs total)

**Dependencies:** None

**Effort:** 45 min

---

## Tier B: Caching Layer

### Task B.1: Implement SchemaCache with In-Memory TTL Storage

**Description:** Build thread-safe, in-memory cache with TTL expiration for schema objects.

**Acceptance Criteria:**
- Class: `SchemaCache` with methods: `get(key, ttl_seconds)`, `set(key, value)`, `invalidate(key)`, `clear()`, `stats()`
- Uses `threading.Lock` for thread-safe access
- Cache stored as dict: `{key: (value, timestamp)}`
- get(key, ttl_seconds) returns cached value IF current_time - timestamp < ttl_seconds, else returns None and marks as expired
- set(key, value) stores (value, time.time()) tuple
- invalidate(key) removes entry immediately
- clear() removes all entries and resets stats
- stats() returns dict: `{hits, misses, total_lookups, hit_rate, evictions, size}`
- WHEN accessed by multiple threads, all operations are atomic (no race conditions)
- WHEN TTL expires, entry is removed on next access (lazy eviction)
- Verification:
  - set("schema_test", {"tables": []})
  - get("schema_test", 10) returns the stored dict
  - get("schema_test", 0) returns None (expired immediately)
  - stats() shows hits=1, misses=1 after above operations

**Dependencies:** None

**Effort:** 45 min

---

### Task B.2: Integrate Schema Caching into get_schema_from_db()

**Description:** Add caching layer to schema introspection so repeated calls return cached schema.

**Acceptance Criteria:**
- Modify `get_schema_from_db()` to:
  1. Check cache first: `cache.get(cache_key, ttl_seconds=config.schema_cache_ttl_seconds)`
  2. IF cache hit, return cached schema
  3. ELSE query DB, cache result, return
- Cache key format: `schema_{database_name}_{mode}` (e.g., "schema_querypilot_target_full")
- Cache TTL configurable via config.schema_cache_ttl_seconds (default: 3600)
- WHEN cache is invalidated (e.g., via admin command), next call re-fetches
- Verification:
  - First call: queries DB, stores cache, returns schema
  - Second call (within TTL): returns cached result (no DB query)
  - Third call (after TTL expires): queries DB again, caches result
  - stats() shows hit_rate increasing with repeated calls

**Dependencies:** Task A.1, Task B.1

**Effort:** 30 min

---

## Tier C: Full Schema Formatting (Mode A)

### Task C.1: Implement format_full_schema() Text Formatter

**Description:** Format complete schema as human-readable text for LLM consumption.

**Acceptance Criteria:**
- Function: `format_full_schema(schema_dict, fk_relationships, include_samples=True, include_warnings=True, include_row_counts=True) -> str`
- Output format:
  ```
  TABLES:

  1. table_name (row_count rows)
     Description: ...
     Columns:
       - column_name type [NOT NULL] [PRIMARY KEY] [, samples: [val1, val2, ...]]
     Foreign Keys:
       - child.col → parent.col
     Indexes: idx1, idx2
     [Warnings: ...]
  ```
- Includes all tables in schema_dict (numbered 1, 2, 3, ...)
- Column list includes type, NOT NULL constraint, PK flag, and (if include_samples=True) up to 5 sample values
- Foreign keys list shows all FKs where this table is parent or child
- Indexes listed by name
- Warnings (if include_warnings=True) shown after each table (see Task C.2)
- Plain-text output (no markdown, no XML tags)
- WHEN include_samples=False, omits all sampled_values
- WHEN include_warnings=False, omits warnings section
- WHEN schema_dict has malformed data, logs warning and skips (never crashes)
- Verification:
  - format_full_schema(test_schema, test_fks) returns string starting with "TABLES:\n"
  - Output includes all 5 tables (customers, products, orders, order_items, reviews)
  - Output includes column types (INT, VARCHAR, DECIMAL, etc.)
  - Output includes FK relationships (orders → customers, order_items → orders, etc.)

**Dependencies:** Task A.1, Task A.3

**Effort:** 60 min

---

### Task C.2: Implement detect_one_to_many_joins() and Warning System

**Description:** Detect one-to-many FK relationships and generate warnings for LLM.

**Acceptance Criteria:**
- Function: `detect_one_to_many_joins(schema_dict, fk_relationships) -> list[tuple[parent, child, risk_level]]`
- FOR each FK relationship, compute: avg_children_per_parent = child_row_count / parent_row_count
- IF avg_children_per_parent > 1.1:
  - IF avg_children_per_parent < 2: risk_level = "low"
  - ELIF avg_children_per_parent < 10: risk_level = "medium"
  - ELSE: risk_level = "high"
- Returns sorted list of (parent_table, child_table, risk_level)
- Handles edge case: parent_row_count == 0 → skip (no data yet)
- Generates warning messages in format:
  ```
  ⚠️ [HIGH RISK: ] parent → child is one-to-many. SUM/COUNT will multiply if not grouped.
  ```
- HIGH RISK warnings emphasized with "⚠️ HIGH RISK:" prefix
- Warnings injected into format_full_schema() output after parent table definition
- Verification:
  - For orders (5000) → order_items (20000): avg = 4, detects as one-to-many, risk="medium"
  - For customers (500) → reviews (1250): avg ≈ 2.5, detects as one-to-many, risk="low"
  - Warnings appear in formatted output near orders table definition

**Dependencies:** Task A.1, Task C.1

**Effort:** 45 min

---

## Tier D: Semantic Layer

### Task D.1: Create app/semantic_layer.yaml Business Term Definitions

**Description:** Define business terms (revenue, active_customer, etc.) with SQL calculations in YAML.

**Acceptance Criteria:**
- File: `app/semantic_layer.yaml`
- Defines at least 5 business terms:
  - `revenue`: SUM(orders.total_amount) WHERE status='paid', referenced_tables=['orders'], alternatives=['total_revenue', 'sales']
  - `order_count`: COUNT(DISTINCT orders.id), referenced_tables=['orders']
  - `average_order_value`: AVG(orders.total_amount) WHERE status='paid', referenced_tables=['orders']
  - `active_customer`: EXISTS (... paid order in last 90 days), referenced_tables=['customers', 'orders']
  - `yoy_growth`: Year-over-year comparison pattern, referenced_tables=['orders']
- Each term has: description, calculation_sql, referenced_tables, alternative_names
- YAML syntax valid and parseable via PyYAML
- All referenced tables exist in seed schema
- Verification:
  - yaml.safe_load(open('app/semantic_layer.yaml')) succeeds
  - Loaded dict has key 'business_terms'
  - Each term has required keys: description, calculation_sql, referenced_tables

**Dependencies:** None

**Effort:** 30 min

---

### Task D.2: Implement SemanticLayerLoader with YAML Parsing

**Description:** Load YAML and provide term detection and lookup.

**Acceptance Criteria:**
- Class: `SemanticLayerLoader(yaml_path)`
- Loads YAML on init; raises ConfigError if file not found or invalid syntax
- Methods:
  - `detect_terms(question: str) -> list[str]`: find term names mentioned in question (case-insensitive, word-boundary matching)
  - `get_term_definition(term_name: str) -> dict`: return {description, calculation_sql, referenced_tables, alternative_names}
  - `get_referenced_tables(term_name: str) -> set[str]`: return set of table names referenced by term
- Builds reverse index on init: synonym → term_name for fast lookup
- detect_terms() uses regex word boundary matching to avoid partial matches
- WHEN term not found in YAML, get_term_definition() returns empty dict (not error)
- Verification:
  - SemanticLayerLoader('app/semantic_layer.yaml').detect_terms("What is the total revenue?") returns ['revenue']
  - detect_terms("Compare revenue and orders this year") returns ['revenue', 'order_count']
  - get_referenced_tables('revenue') returns {'orders'}
  - get_referenced_tables('active_customer') returns {'customers', 'orders'}

**Dependencies:** Task D.1

**Effort:** 40 min

---

### Task D.3: Implement inject_semantic_terms() Context Injection

**Description:** Prepend business term definitions to schema context.

**Acceptance Criteria:**
- Function: `inject_semantic_terms(schema_context: str, detected_terms: list[str], semantic_loader: SemanticLayerLoader) -> str`
- Prepends "BUSINESS TERMS:" section to schema_context
- FOR each term in detected_terms:
  - Include description and calculation_sql inline
  - Format: "- term_name: description. Calculation: calculation_sql\n"
- IF detected_terms is empty, returns schema_context unchanged
- Appends "TABLES:" section before existing schema
- WHEN a detected term references tables not in current schema, logs warning (does not fail)
- Verification:
  - inject_semantic_terms(schema_context, ['revenue'], loader)
    - Output starts with "BUSINESS TERMS:\n- revenue: Total revenue..."
    - Includes calculation SQL
    - Followed by "TABLES:\n" and original schema_context
  - inject_semantic_terms(schema_context, [], loader) returns schema_context unchanged

**Dependencies:** Task D.2

**Effort:** 30 min

---

## Tier E: Embedding-Based Retrieval (Mode B)

### Task E.1: Define EmbeddingProvider Abstract Interface and Concrete Implementations

**Description:** Create pluggable interface for embedding providers (OpenAI, local, Bedrock).

**Acceptance Criteria:**
- Abstract class: `EmbeddingProvider` with method `async embed(text: str) -> list[float]`
- Implementation: `OpenAIEmbeddings(api_key, model='text-embedding-3-small')`
  - Uses openai library to call embeddings API
  - Returns embedding as list[float]
  - Handles: AuthenticationError → raises EmbeddingError, timeout → raises EmbeddingError
- Implementation: `LocalEmbeddings(model='all-MiniLM-L6-v2')`
  - Uses sentence-transformers (HuggingFace)
  - Lazy-loads model on first embed() call
  - Returns embedding as list[float]
- Both implementations produce consistent-length embeddings (1536 for OpenAI, varies for local)
- WHEN instantiated with invalid credentials, raises ConfigError immediately
- Verification:
  - OpenAIEmbeddings with valid key embeds "test text" successfully
  - LocalEmbeddings embeds "test text" without network calls
  - Both return list[float] with consistent length

**Dependencies:** None

**Effort:** 45 min

---

### Task E.2: Implement store_table_embeddings() with pgvector Storage

**Description:** Embed table descriptions and store in pgvector table for semantic search.

**Acceptance Criteria:**
- Function: `async store_table_embeddings(schema_dict, embedding_provider, target_db_url, vector_dimension=1536) -> int`
- Steps:
  1. CREATE EXTENSION IF NOT EXISTS vector
  2. CREATE table_embeddings table: (table_name TEXT PK, description TEXT, embedding VECTOR(vector_dimension), created_at TIMESTAMP)
  3. FOR each table in schema_dict:
     - Create description: "{table_name}: {description}. Columns: {col1, col2, ...}"
     - Call embedding_provider.embed(description) → embedding
     - INSERT OR UPDATE table_embeddings
  4. CREATE INDEX on embedding column (HNSW or IVFFLAT)
- Returns count of stored embeddings
- WHEN pgvector extension not available, raises ConfigError with install instructions
- WHEN embedding fails, raises EmbeddingError with provider-specific message
- Verification:
  - Called with 5-table schema and OpenAI embeddings
  - Returns 5 (stored all tables)
  - Query SELECT COUNT(*) FROM table_embeddings returns 5
  - SELECT embedding FROM table_embeddings WHERE table_name='orders' returns non-null vector

**Dependencies:** Task A.1, Task E.1

**Effort:** 60 min

---

### Task E.3: Implement retrieve_tables_by_embedding() Vector Search

**Description:** Embed question and retrieve top-k semantically similar tables via pgvector.

**Acceptance Criteria:**
- Function: `async retrieve_tables_by_embedding(question: str, embedding_provider, target_db_url, top_k=5) -> list[str]`
- Steps:
  1. Call embedding_provider.embed(question) → question_embedding
  2. Query pgvector: SELECT table_name FROM table_embeddings ORDER BY embedding <-> question_embedding LIMIT top_k
  3. Return list of table_name strings
- Uses pgvector distance operator `<->` (vector_cosine distance)
- WHEN fewer than top_k tables exist, returns all available
- WHEN pgvector query fails, raises EmbeddingError
- WHEN embedding_provider fails, raises EmbeddingError
- Verification:
  - Question: "How much revenue did we make from each customer?"
    - Retrieves tables: ['orders', 'order_items', 'customers', ...] (orders and order_items should rank high)
  - Question: "What is the rating for electronics?"
    - Retrieves tables: ['reviews', 'products', ...] (reviews and products should rank high)

**Dependencies:** Task E.2

**Effort:** 40 min

---

## Tier F: FK Expansion and Integration

### Task F.1: Implement expand_schema_via_fk() for FK Traversal

**Description:** Traverse FK relationships to expand table set and preserve join paths.

**Acceptance Criteria:**
- Function: `expand_schema_via_fk(initial_tables: set, fk_relationships: list, schema_dict: dict, max_depth=1) -> tuple[set, dict]`
- BFS traversal from initial_tables:
  - FOR each table at depth D < max_depth, find all FKs where table is parent or child
  - Add related tables to expanded set
  - Track visited tables to prevent cycles
- Returns: (expanded_table_set, join_paths_info)
  - expanded_table_set: set of all tables including initial and expanded
  - join_paths_info: dict mapping table → list of {target, type (has_many/belongs_to), fk_info}
- WHEN max_depth=1 (default), expands only direct neighbors
- WHEN max_depth=2, expands to 2-hop neighbors (and so on)
- Prevents infinite loops by tracking visited tables within a path
- WHEN FK metadata incomplete, logs warning and continues
- Verification:
  - expand_schema_via_fk({'orders'}, fks, schema, max_depth=1) returns ({'orders', 'customers', 'order_items'}, {...})
  - expand_schema_via_fk({'order_items'}, fks, schema, max_depth=1) returns ({'order_items', 'orders', 'products'}, {...})
  - expand_schema_via_fk({'customers'}, fks, schema, max_depth=2) returns all tables (2 hops away)

**Dependencies:** Task A.3

**Effort:** 50 min

---

### Task F.2: Integrate Mode B Retrieval into LangGraph retrieve_schema Node

**Description:** Wire embedding-based retrieval into the LangGraph agent.

**Acceptance Criteria:**
- Modify `retrieve_schema()` LangGraph node to:
  1. Check config.schema_retrieval_mode (full, embedding, auto)
  2. IF auto, determine mode based on table count (> 20 → embedding)
  3. IF mode == full: use format_full_schema()
  4. IF mode == embedding:
     - Call retrieve_tables_by_embedding(question, ...)
     - Call expand_schema_via_fk() on retrieved tables
     - Filter schema_dict to expanded tables
     - Format via format_full_schema()
  5. Cache result with TTL
  6. Return schema_context in state
- Configurable: mode, top_k, max_depth, embedding_provider via config
- WHEN embedding fails, fall back to Mode A if configured (optional)
- Verification:
  - Question about "orders and revenue" with > 20 table schema:
    - retrieve_schema() uses Mode B
    - Returns schema_context with ~5–10 relevant tables, not all tables
    - Includes orders, customers, order_items
  - Schema cache hit on repeated questions reduces latency

**Dependencies:** Task A.1, Task B.2, Task C.1, Task E.3, Task F.1

**Effort:** 60 min

---

## Tier G: Metrics and Testing

### Task G.1: Implement compute_schema_retrieval_recall() Metric in eval/metrics.py

**Description:** Create evaluation metric to measure schema retrieval effectiveness.

**Acceptance Criteria:**
- Function: `compute_schema_retrieval_recall(retrieved_tables: set, expected_tables: set) -> dict`
- Computes:
  - common = retrieved_tables ∩ expected_tables
  - recall = len(common) / len(expected_tables)  (IF expected_tables empty, return 1.0)
  - precision = len(common) / len(retrieved_tables)  (IF retrieved_tables empty, return 0.0)
  - missing_tables = expected_tables - retrieved_tables
  - over_retrieved_tables = retrieved_tables - expected_tables
- Returns dict:
  ```python
  {
      'recall': float (0-1),
      'precision': float (0-1),
      'retrieved_count': int,
      'expected_count': int,
      'common_count': int,
      'missing_tables': list,
      'over_retrieved_tables': list
  }
  ```
- WHEN expected_tables is empty (edge case), recall = 1.0 (perfect for no requirements)
- Verification:
  - retrieved={'orders', 'customers', 'products'}, expected={'orders', 'customers'}
    - recall = 1.0, precision = 2/3 ≈ 0.667
  - retrieved={'orders'}, expected={'orders', 'customers', 'order_items'}
    - recall = 1/3 ≈ 0.333, precision = 1.0

**Dependencies:** None

**Effort:** 20 min

---

### Task G.2: Unit Tests for Schema Retrieval and Formatting

**Description:** Write comprehensive unit tests for schema retrieval components.

**Acceptance Criteria:**
- Test file: `tests/tools/test_schema_retrieval.py`
- Test `get_schema_from_db()`:
  - Returns all 5 tables with correct structure
  - Includes row counts, descriptions, FKs
  - Includes sample values for low-cardinality columns
  - Raises SchemaError on connection failure or missing table
- Test `format_full_schema()`:
  - Output includes all tables in order
  - Includes column types, nullable, PK flags
  - Includes sample values (if include_samples=True)
  - Omits samples (if include_samples=False)
  - Includes one-to-many warnings (if include_warnings=True)
- Test `detect_one_to_many_joins()`:
  - Identifies orders → order_items as one-to-many
  - Computes risk levels correctly
  - Handles zero row counts gracefully
- Test `expand_schema_via_fk()`:
  - Expands initial tables to include directly connected tables
  - Prevents cycles (visiting table twice)
  - Respects max_depth parameter
- Test `SchemaCache`:
  - Set/get operations work
  - TTL expiration works
  - Thread-safe with concurrent access
  - Stats tracking accurate
- Minimum 30 test cases, 100% coverage for schema.py, cache.py, formatter.py

**Dependencies:** All schema and cache tasks

**Effort:** 90 min

---

### Task G.3: Integration Tests: Full Schema Retrieval Pipeline

**Description:** Test full schema retrieval pipeline end-to-end with multiple scenarios.

**Acceptance Criteria:**
- Test file: `tests/agent/test_retrieve_schema_integration.py`
- Test scenario 1: Small schema (≤20 tables) → Mode A full schema
  - Mock schema_dict with 5 tables
  - retrieve_schema() node returns formatted full schema
  - Output includes all tables and warnings
- Test scenario 2: Large schema (>20 tables) → Mode B embedding
  - Mock schema_dict with 25+ tables
  - Seed pgvector with embeddings
  - retrieve_schema() node uses embedding retrieval
  - Output includes only relevant tables
- Test scenario 3: Semantic term injection
  - Question mentions "revenue"
  - Semantic layer detected and injected
  - Schema context prepended with revenue definition
  - Referenced tables (orders) included
- Test scenario 4: FK expansion
  - Retrieved tables expanded via FK relationships
  - join_paths_info returned correctly
- Test scenario 5: Cache hit/miss
  - First call: cache miss, queries DB
  - Second call: cache hit, returns immediately
  - After TTL: cache miss again
- Minimum 10 integration test cases

**Dependencies:** All tasks up to G.2

**Effort:** 75 min

---

## Tier H: Configuration and Documentation

### Task H.1: Update app/config.py with Schema Retrieval Settings

**Description:** Add configuration fields for schema retrieval mode, cache TTL, embedding provider, etc.

**Acceptance Criteria:**
- Add to Config class:
  - `schema_retrieval_mode: str = "auto"` (full, embedding, auto)
  - `schema_retrieval_full_table_limit: int = 20` (threshold for auto-mode)
  - `schema_cache_ttl_seconds: int = 3600` (default 1 hour)
  - `embedding_provider: Optional[str] = None` (openai, local)
  - `embedding_model: str = "text-embedding-3-small"`
  - `embedding_top_k: int = 5`
  - `embedding_max_depth: int = 1`
  - `include_schema_samples: bool = True`
  - `include_schema_warnings: bool = True`
  - `semantic_layer_yaml_path: str = "app/semantic_layer.yaml"`
- validate_required_vars() checks:
  - IF embedding_provider is set, verify credentials (OPENAI_API_KEY, etc.)
  - semantic_layer.yaml file exists
- Config.get_config() returns singleton with new fields
- Verification:
  - Config() loads from .env with schema_retrieval_mode="embedding"
  - Validation passes with EMBEDDING_PROVIDER="openai" and OPENAI_API_KEY set
  - Validation fails with helpful error if semantic_layer.yaml missing

**Dependencies:** None

**Effort:** 30 min

---

### Task H.2: Create .env.example Documentation for Schema Retrieval

**Description:** Document all new environment variables in .env.example.

**Acceptance Criteria:**
- Update `.env.example` with new schema retrieval settings:
  ```
  # Schema Retrieval
  SCHEMA_RETRIEVAL_MODE=auto  # full, embedding, auto
  SCHEMA_RETRIEVAL_FULL_TABLE_LIMIT=20
  SCHEMA_CACHE_TTL_SECONDS=3600
  
  # Embedding (required if SCHEMA_RETRIEVAL_MODE=embedding or auto with >20 tables)
  EMBEDDING_PROVIDER=openai  # openai, local
  EMBEDDING_MODEL=text-embedding-3-small
  EMBEDDING_TOP_K=5
  EMBEDDING_MAX_DEPTH=1
  
  # Schema Formatting
  INCLUDE_SCHEMA_SAMPLES=true
  INCLUDE_SCHEMA_WARNINGS=true
  SEMANTIC_LAYER_YAML_PATH=app/semantic_layer.yaml
  ```
- Include inline comments explaining each variable
- Document conditions (e.g., "required if embedding mode")
- File is human-readable and self-documenting
- Verification: Developers can copy .env.example to .env, fill in values, and have complete config

**Dependencies:** Task H.1

**Effort:** 15 min

---

### Task H.3: Create app/verify_schema_retrieval.py Verification Script

**Description:** Create verification script to check schema retrieval setup and configuration.

**Acceptance Criteria:**
- Script: `python -m app.verify_schema_retrieval`
- Performs checks:
  1. Database connectivity: Connect to target DB, query information_schema
  2. Schema introspection: Verify all 5 tables present with expected columns/FKs
  3. Caching: Instantiate SchemaCache, test get/set/TTL operations
  4. Semantic layer: Load YAML, verify business terms loaded correctly
  5. IF embedding mode enabled:
     - Verify embedding provider credentials
     - Test embed("sample text") successfully
     - Check pgvector extension present (if not, suggest install)
  6. Cache performance: Simulate cache hits/misses, report hit rate
- Output format: checkmark (✓) or X for each check, with messages
- Exit code 0 if all checks pass, 1 if any fail
- WHEN check fails, provide remediation steps (e.g., "Install pgvector: CREATE EXTENSION pgvector;")
- Verification:
  - `python -m app.verify_schema_retrieval` runs to completion
  - All checks pass for properly configured system
  - Provides actionable error messages if checks fail

**Dependencies:** All schema retrieval tasks

**Effort:** 45 min

---

## Summary by Component

| Component | Tasks | Effort | Count |
|---|---|---|---|
| Schema Introspection | A.1–A.3 | 3h | 3 |
| Caching | B.1–B.2 | 1.25h | 2 |
| Full Schema (Mode A) | C.1–C.2 | 1.75h | 2 |
| Semantic Layer | D.1–D.3 | 1.5h | 3 |
| Embedding (Mode B) | E.1–E.3 | 2.25h | 3 |
| FK Expansion & Integration | F.1–F.2 | 1.67h | 2 |
| Metrics & Testing | G.1–G.3 | 3h | 3 |
| Configuration & Docs | H.1–H.3 | 1.5h | 3 |
| **TOTAL** | **A–H** | **~16.5h** | **21 tasks** |

---

## Task Execution Order (Critical Path)

1. **Foundation (Parallel):**
   - A.1: get_schema_from_db() — blocks all downstream schema work
   - A.3: get_fk_relationships() — blocks FK expansion and Mode A formatting
   - D.1: Create semantic_layer.yaml — needed for D.2

2. **Core Subsystems (Parallel after foundation):**
   - A.2: get_table_metadata() — after A.1
   - B.1: SchemaCache — independent
   - C.1: format_full_schema() — after A.1, A.3
   - E.1: EmbeddingProvider interface — independent
   - H.1: Config updates — independent

3. **Feature Integration (Parallel):**
   - B.2: Cache integration — after B.1, A.1
   - C.2: One-to-many warnings — after C.1
   - D.2: SemanticLayerLoader — after D.1
   - E.2: store_table_embeddings() — after E.1, A.1
   - F.1: FK expansion — after A.3
   - D.3: inject_semantic_terms() — after D.2

4. **LangGraph Integration:**
   - F.2: Integrate into retrieve_schema node — after B.2, C.1, E.3, F.1, D.3

5. **Testing & Verification (Last):**
   - G.1: Recall metric — independent
   - G.2: Unit tests — after all implementation tasks
   - G.3: Integration tests — after F.2
   - H.2: .env.example — after H.1
   - H.3: Verification script — after all tasks

---

## Estimated Effort Breakdown

- **Async DB queries & metadata extraction**: ~8 hours (A.1–A.2)
- **Caching & performance**: ~1.5 hours (B.1–B.2)
- **Schema formatting & warnings**: ~2 hours (C.1–C.2)
- **Semantic layer (YAML + loader)**: ~1.5 hours (D.1–D.3)
- **Embeddings & pgvector**: ~2.5 hours (E.1–E.3)
- **FK traversal & agent integration**: ~2 hours (F.1–F.2)
- **Testing & metrics**: ~3 hours (G.1–G.3)
- **Config & docs**: ~1.5 hours (H.1–H.3)
- **Buffer for debugging/refinement**: ~2 hours

**Total: ~16–18 hours of focused engineering work**

---

## Success Criteria (All Tasks Complete)

✓ All 10 requirements (R1–R10) have acceptance criteria met by at least one task
✓ Schema introspection accurate (metadata, FKs, samples extracted correctly)
✓ Caching functional with TTL and thread-safety
✓ Mode A produces human-readable, complete schema text
✓ Mode B uses embeddings for semantic retrieval and expands via FKs
✓ Semantic layer terms detected and injected into schema context
✓ One-to-many warnings generated for high-risk joins
✓ Recall metric computed for evaluation
✓ All unit and integration tests pass
✓ Configuration driven entirely by environment variables
✓ Verification script confirms setup is correct
✓ LangGraph agent's retrieve_schema node uses new schema retrieval system

</content>
