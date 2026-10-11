# Requirements Document

## Introduction

**Feature:** Schema Retrieval and Semantic Layer (Step 2 of QueryPilot Build Order)

Step 2 of the QueryPilot build order enhances the baseline text-to-SQL system (Step 1) with intelligent schema retrieval and a semantic layer to resolve business term ambiguity. This step introduces two operational modes: full schema retrieval for small databases (≤20 tables) and embedding-based retrieval for large schemas (>20 tables), augmented with a semantic layer that defines business terms and their calculations, and FK expansion for join path preservation.

The schema retrieval system includes caching with TTL expiration, one-to-many fan-out warnings, and measurable recall metrics to evaluate schema retrieval effectiveness. This directly improves LLM accuracy by ensuring the correct tables are available in context and prevents hallucination of non-existent columns or incorrect join paths.

## Glossary

- **Schema Retrieval**: The process of fetching relevant database tables, columns, types, foreign keys, and sample values from the target database and returning them in a format optimized for LLM consumption.
- **Mode A (Full Schema)**: Retrieval mode for small schemas (≤20 tables) where the complete schema is formatted and included in prompts without filtering.
- **Mode B (Embedding-Based Retrieval)**: Retrieval mode for large schemas (>20 tables) where table descriptions are embedded, searched semantically, and expanded via FK relationships to preserve join paths.
- **Semantic Layer**: A YAML-defined configuration of business terms (e.g., "revenue", "active_customer") with their SQL calculations and referenced tables, injected into schema context to resolve ambiguity.
- **Foreign Key (FK) Expansion**: The process of traversing FK relationships to automatically include related tables (join paths) when retrieving schema, preventing missing tables needed for joins.
- **One-to-Many Relationship**: A database relationship where one row in the parent table corresponds to multiple rows in the child table, creating a fan-out risk that can double-count aggregations if not handled carefully (e.g., orders → order_items).
- **Fan-Out Warning**: A message injected into the schema context warning the LLM about one-to-many relationships that could lead to incorrect aggregation if carelessly joined.
- **Schema Cache**: In-memory (or Redis) storage of retrieved schemas with TTL expiration to avoid repeated database queries.
- **Embedding Provider**: A pluggable service (OpenAI embeddings, local embeddings, etc.) that converts table descriptions into dense vector representations for semantic search.
- **pgvector**: PostgreSQL extension for storing and searching embeddings, used to store and retrieve table descriptions by semantic similarity.
- **Schema Retrieval Recall**: A metric measuring the proportion of required tables that the schema retrieval system successfully identified: (tables_retrieved ∩ tables_expected) / len(tables_expected).

## Requirements

### Requirement 1: Database Schema Introspection

**User Story:** As a schema retrieval system, I want to extract comprehensive metadata from the target database so that I can provide the LLM with accurate, up-to-date table and column information without hallucination.

#### Acceptance Criteria

1. WHEN get_schema_from_db() is called, THE Schema_Retriever SHALL query `information_schema.tables` and `information_schema.columns` to extract all public schema tables and their columns.

2. WHEN the Schema_Retriever retrieves columns, FOR EACH column, THE Schema_Retriever SHALL extract and include: column name, data type (e.g., INT, VARCHAR, DECIMAL), NOT NULL constraint status, and default value if present.

3. WHEN the Schema_Retriever retrieves table metadata, THE Schema_Retriever SHALL query `information_schema.table_constraints` and `information_schema.key_column_usage` to identify and extract:
   - Primary key column(s) for each table
   - Foreign key constraints (referenced table, referenced column, FK column)
   - Unique constraints

4. WHEN the Schema_Retriever retrieves column descriptions, THE Schema_Retriever SHALL query `pg_description` catalog to extract comments on tables and columns if present; these descriptions provide business context (e.g., "total_amount is gross before discounts").

5. WHEN the Schema_Retriever retrieves sample values, FOR low-cardinality columns (distinct count < 20), THE Schema_Retriever SHALL query `SELECT DISTINCT column_name FROM table ORDER BY column_name LIMIT 20;` and include sample values in column metadata (e.g., status column has values ['paid', 'refunded', 'cancelled']).

6. WHEN get_fk_relationships() is called, THE Schema_Retriever SHALL return all foreign key relationships as a list of tuples: (parent_table, parent_column, child_table, child_column, constraint_name).

7. WHEN the Schema_Retriever completes introspection, EACH table record SHALL include: table_name, columns (list with full metadata), pk_columns, fk_relationships, description (if available), row_count (estimated via pg_stat_user_tables), and sampled_values (for low-cardinality columns).

8. WHEN introspection is called with a table that does not exist, THE Schema_Retriever SHALL raise SchemaError with message "Table <name> not found in target database".

9. WHEN introspection encounters a database error (connection, permission), THE Schema_Retriever SHALL raise SchemaError with descriptive message and never expose raw DB error to caller.

### Requirement 2: Schema Caching with TTL

**User Story:** As a performance optimizer, I want schema caching with TTL expiration so that I can reduce database load while ensuring schema is not stale beyond a configurable interval.

#### Acceptance Criteria

1. WHEN SchemaCache is instantiated, THE Cache SHALL initialize as an in-memory dict-based cache using Python's threading.Lock for thread-safe access.

2. WHEN cache_schema(key: str, schema: dict, ttl_seconds: int = 3600) is called, THE Cache SHALL store the schema dict with the current timestamp and TTL duration.

3. WHEN get_cached_schema(key: str) is called:
   - IF key exists AND current_time - timestamp < ttl_seconds, THE Cache SHALL return the cached schema
   - IF key exists AND current_time - timestamp >= ttl_seconds, THE Cache SHALL delete the entry and return None (cache expired)
   - IF key does not exist, THE Cache SHALL return None

4. WHEN invalidate_cache(key: str) is called, THE Cache SHALL immediately remove the entry from cache; IF key does not exist, no error is raised.

5. WHEN clear_all_cache() is called, THE Cache SHALL remove all entries and reset internal state.

6. THE Cache SHALL NOT use mutable objects as keys; string keys (e.g., schema_{database_name}) are enforced via assertion.

7. WHEN cache statistics are queried (hit_count, miss_count, avg_ttl), THE Cache SHALL return accurate counts for monitoring; these stats SHALL be available via cache.stats() method.

8. WHEN the Cache is used in a multi-threaded context, THE Cache operations (get, set, invalidate) SHALL be atomic and thread-safe; no race conditions.

9. OPTIONAL (for later step): Redis-backed cache support via `RedisSchemaCache` subclass shall be added without modifying in-memory cache interface.

### Requirement 3: Mode A – Full Schema Retrieval (≤20 Tables)

**User Story:** As an LLM context manager, I want to format and include the complete schema for small databases so that the LLM has all necessary information to generate correct SQL without retrieval filtering.

#### Acceptance Criteria

1. WHEN format_full_schema(schema_dict, include_samples=True, include_warnings=True) is called, THE Schema_Formatter SHALL return a human-readable string formatted as:
   ```
   TABLES:

   1. customers (500 rows)
      Description: Base customer dimension; one row per unique customer.
      Columns:
        - id INT PRIMARY KEY
        - name VARCHAR(255) NOT NULL
        - email VARCHAR(255) UNIQUE, samples: ['john.doe@example.com', 'jane.smith@example.com', ...]
        - state VARCHAR(2), samples: ['CA', 'NY', 'TX', ...]
        - region VARCHAR(50), samples: ['West', 'Northeast', ...]
        - created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
      Foreign Keys: none
      Indexes: idx_customers_email

   2. orders (5000 rows)
      Description: Order transactions; one row per customer order.
      Columns:
        - id INT PRIMARY KEY
        - customer_id INT FOREIGN KEY → customers.id
        - order_date DATE
        - status VARCHAR(50), samples: ['paid', 'refunded', 'cancelled']
        - total_amount DECIMAL(10,2)
      Foreign Keys:
        - orders.customer_id → customers.id
      Indexes: idx_orders_customer_id, idx_orders_order_date
      WARNING: orders → order_items is one-to-many. SUM(order_total) will multiply if not grouped correctly.

   ... (remaining tables)
   ```

2. WHEN format_full_schema() includes column samples, FOR low-cardinality columns (distinct count < 20), THE Formatter SHALL list distinct sample values inline (up to 5 examples) to show valid value domain to the LLM.

3. WHEN format_full_schema() includes foreign key information, THE Formatter SHALL list all FK relationships in a structured way (e.g., "orders.customer_id → customers.id") for clarity.

4. WHEN format_full_schema() includes warnings, THE Formatter SHALL call detect_one_to_many_joins(schema_dict) to identify and include warnings for all one-to-many relationships (see Requirement 7).

5. WHEN format_full_schema() is called, the returned string SHALL be plain-text (no markdown, no XML), suitable for direct injection into LLM prompts.

6. WHEN the schema_dict contains missing or malformed data (e.g., column without name), THE Formatter SHALL handle gracefully: log warning and skip problematic entry (never crash).

7. WHEN format_full_schema() is called with include_samples=False, THE Formatter SHALL omit all sample values from output.

8. WHEN format_full_schema() is called with include_warnings=False, THE Formatter SHALL omit all one-to-many warnings from output.

### Requirement 4: Mode B – Embedding-Based Retrieval for Large Schemas (>20 Tables)

**User Story:** As a schema retriever for large databases, I want to embed table descriptions and retrieve semantically relevant tables so that the LLM receives only necessary context without overwhelming it with hundreds of table definitions.

#### Acceptance Criteria

1. WHEN initialize_embeddings(embedding_provider: str, embedding_model: str) is called, THE Embedding_Manager SHALL:
   - IF embedding_provider == "openai": instantiate OpenAIEmbeddings with provided model (default: "text-embedding-3-small")
   - IF embedding_provider == "local": instantiate LocalEmbeddings (e.g., using sentence-transformers) with provided model
   - Raise ConfigError if provider not supported or credentials missing

2. WHEN store_table_embeddings(schema_dict, embedding_provider, embedding_model, config) is called, THE Embedding_Manager SHALL:
   - FOR each table in schema_dict, create a description string: "{table_name}: {description}. Columns: {comma_separated_column_names}"
   - Embed each description using embedding_provider to a dense vector
   - Insert into pgvector table: table_embeddings (table_name TEXT, description TEXT, embedding VECTOR(1536), created_at TIMESTAMP)
   - CREATE INDEX ON embedding column using pgvector's HNSW or IVFFLAT index for efficient search
   - ON success, return count of stored embeddings
   - ON failure (embedding API error, DB error), raise EmbeddingError with descriptive message

3. WHEN retrieve_tables_by_embedding(question: str, top_k: int = 5, embedding_provider, embedding_model, config) is called, THE Retrieval_System SHALL:
   - Embed the question using the same embedding_provider and embedding_model
   - Query pgvector: `SELECT table_name, description FROM table_embeddings ORDER BY embedding <-> question_embedding LIMIT top_k;` (using pgvector's vector distance operator)
   - Return list of (table_name, description) tuples for top-k matches
   - Handle edge case: if pgvector index is stale/missing, fall back to full table scan or raise EmbeddingError

4. WHEN retrieve_tables_by_embedding() is called, THE Retrieval_System SHALL also call expand_schema_via_fk() on the retrieved table set to include related tables via FK relationships (see Requirement 6).

5. WHEN embedding storage fails (e.g., pgvector extension not installed), THE Embedding_Manager SHALL raise ConfigError with actionable message: "pgvector extension required for Mode B. Install with: CREATE EXTENSION pgvector;"

6. WHEN embedding retrieval fails (e.g., question_embedding API timeout), THE Retrieval_System SHALL raise EmbeddingError and fall back to Mode A (full schema) if configured to do so.

7. WHEN top_k parameter is provided, THE Retrieval_System SHALL return at most top_k tables; if fewer than top_k tables exist, return all available.

### Requirement 5: Semantic Layer with Business Term Definitions

**User Story:** As a business analyst, I want to define business terms (revenue, active_customer, etc.) with their SQL calculations so that the LLM understands domain-specific metrics without guessing.

#### Acceptance Criteria

1. WHEN app/semantic_layer.yaml is loaded, THE Semantic_Loader SHALL parse YAML with structure:
   ```yaml
   business_terms:
     revenue:
       description: "Total revenue from paid orders only, computed as SUM of order totals where status='paid'"
       calculation_sql: "SUM(orders.total_amount) FILTER (WHERE orders.status = 'paid')"
       referenced_tables: ["orders"]
       alternative_names: ["total_revenue", "sales"]

     order_count:
       description: "Count of all orders regardless of status"
       calculation_sql: "COUNT(DISTINCT orders.id)"
       referenced_tables: ["orders"]

     active_customer:
       description: "Customer with at least one paid order in the last 90 days"
       calculation_sql: "EXISTS (SELECT 1 FROM orders WHERE orders.customer_id = customers.id AND orders.status = 'paid' AND orders.order_date >= CURRENT_DATE - INTERVAL '90 days')"
       referenced_tables: ["customers", "orders"]

     average_order_value:
       description: "Average total amount per paid order"
       calculation_sql: "AVG(orders.total_amount) FILTER (WHERE orders.status = 'paid')"
       referenced_tables: ["orders"]
   ```

2. WHEN the Semantic_Loader parses the YAML, FOR each business term, THE Loader SHALL extract: description, calculation_sql, referenced_tables, and alternative_names (list of synonyms).

3. WHEN detect_semantic_terms(question: str, semantic_layer: dict) is called, THE Term_Detector SHALL:
   - Tokenize question into words
   - FOR each business_term, check if term name or any alternative_name matches (case-insensitive) in question
   - Return list of matched terms with their definitions

4. WHEN inject_semantic_terms(schema_context: str, detected_terms: list[str], semantic_layer: dict) is called, THE Term_Injector SHALL:
   - Prepend a "BUSINESS TERMS" section to schema_context containing definitions for all detected_terms
   - Format example:
     ```
     BUSINESS TERMS:
     - revenue: Total revenue from paid orders only. Calculation: SUM(orders.total_amount) WHERE orders.status='paid'
     - active_customer: Customer with at least one paid order in the last 90 days
     ```
   - Return augmented schema_context

5. WHEN a business term is detected but required tables are missing from current schema context, THE Term_Injector SHALL automatically expand schema to include referenced_tables from that term.

6. WHEN semantic_layer.yaml does not exist or is malformed, THE Semantic_Loader SHALL raise ConfigError with message "semantic_layer.yaml not found or invalid YAML syntax".

7. WHEN a detected term has referenced_tables not present in the current schema, THE Term_Injector SHALL log warning: "Term '{term}' references tables {missing}, which are not in current schema context" and continue (not fail).

### Requirement 6: FK Expansion and Join Path Preservation

**User Story:** As a join path optimizer, I want to automatically expand retrieved schema to include related tables via foreign keys so that the LLM doesn't need to infer join relationships or search for additional tables.

#### Acceptance Criteria

1. WHEN expand_schema_via_fk(initial_tables: set[str], fk_relationships: list, schema_dict: dict, max_depth: int = 1) is called, THE FK_Expander SHALL:
   - Start with initial_tables (from embedding retrieval or explicit selection)
   - FOR each table in current set, find all FK relationships where: parent_table OR child_table matches current table
   - Add referenced tables to the expanded set (up to max_depth levels of traversal)
   - Prevent infinite recursion by tracking visited tables

2. WHEN FK_Expander traverses relationships, THE FK_Expander SHALL preserve one-to-one and one-to-many source relationships:
   - If orders.customer_id → customers.id, include customers when orders is in the set
   - If orders.id ← order_items.order_id, include order_items when orders is in the set
   - Return a mapping: {parent_table: [child_tables], child_table: [parent_tables]} for reference

3. WHEN max_depth is 1 (default), THE FK_Expander SHALL expand only directly connected tables (1-hop neighbors).

4. WHEN max_depth > 1, THE FK_Expander SHALL recursively expand to N-hop neighbors (e.g., max_depth=2 includes orders → order_items → products).

5. WHEN FK_Expander detects a cycle (e.g., A → B → A), THE FK_Expander SHALL NOT revisit the same table within the same traversal path; cycles are safely prevented.

6. WHEN FK_Expander identifies all expanded tables, THE FK_Expander SHALL return: (expanded_table_set, join_paths_info) where join_paths_info documents how each table connects.

7. WHEN a table in expanded set has missing FK metadata, THE FK_Expander SHALL log warning and continue (resilient to incomplete metadata).

### Requirement 7: One-to-Many Warning System

**User Story:** As a data quality guardian, I want to warn the LLM about one-to-many relationships so that it avoids double-counting when aggregating data.

#### Acceptance Criteria

1. WHEN detect_one_to_many_joins(schema_dict) is called, THE Warning_Detector SHALL:
   - Identify all FK relationships
   - FOR each FK relationship (parent → child), determine if it's one-to-many: check child row count / parent row count > 1.1 (indicating multiple children per parent)
   - Return list of one-to-many relationships: [(parent_table, child_table, risk_level), ...]
   - risk_level: "low" (< 2 avg children/parent), "medium" (2–10 avg), "high" (> 10 avg)

2. WHEN the Warning_Detector generates warnings, THE Warning_Detector SHALL format each as:
   ```
   WARNING: {parent_table} → {child_table} is one-to-many (avg {n} items per {parent}). 
   SUM/COUNT will multiply if not grouped. Use DISTINCT or subquery to avoid double-counting.
   ```

3. WHEN warnings are included in schema context, THE warnings SHALL appear immediately after the relevant table's definition so the LLM encounters them contextually.

4. WHEN a one-to-many relationship has risk_level="high", THE warning SHALL be emphasized: "⚠️ HIGH RISK: ..."

5. WHEN detect_one_to_many_joins() is called but row count statistics are not available (e.g., tables newly created), THE Detector SHALL estimate based on FK cardinality metadata if available, or log "row count unavailable for join risk assessment".

6. WHEN one-to-many warnings are generated, THE warnings SHALL NOT prevent schema retrieval; they are advisory only.

### Requirement 8: Schema Retrieval Recall Metric

**User Story:** As an evaluation engineer, I want to measure schema retrieval effectiveness so that I can quantify how many required tables are successfully retrieved.

#### Acceptance Criteria

1. WHEN compute_schema_retrieval_recall(retrieved_tables: set[str], expected_tables: set[str]) is called, THE Metric_Computer SHALL:
   - Compute intersection: common_tables = retrieved_tables ∩ expected_tables
   - Return recall: len(common_tables) / len(expected_tables) as a float (0.0 to 1.0)
   - Handle edge case: if expected_tables is empty, return 1.0 (perfect recall for no requirements)

2. WHEN recall is computed, THE Metric_Computer SHALL also return precision: len(common_tables) / len(retrieved_tables) (proportion of retrieved tables that were actually needed).

3. WHEN schema retrieval recall metric is computed, THE Metric_Computer SHALL be added to eval/metrics.py as a reusable function for evaluation harness.

4. WHEN recall and precision are logged, THE logging SHALL include: retrieved_count, expected_count, common_count, recall_pct, precision_pct.

5. WHEN a table is retrieved but not expected (precision < 1.0), THE Metric_Computer SHALL log it as "over-retrieval" for analysis; this may reduce context length but typically does not harm accuracy.

### Requirement 9: Configuration and Tuning

**User Story:** As a deployment engineer, I want to configure schema retrieval mode, cache TTL, embedding provider, and other parameters via environment variables.

#### Acceptance Criteria

1. WHEN the Application starts, THE Configuration_Manager SHALL read and validate schema retrieval settings:
   - `SCHEMA_RETRIEVAL_MODE`: one of "full", "embedding", "auto" (default: "auto")
     - "auto" uses "full" for ≤20 tables, "embedding" for >20 tables
   - `SCHEMA_RETRIEVAL_FULL_TABLE_LIMIT`: threshold for auto-detection (default: 20)
   - `SCHEMA_CACHE_TTL_SECONDS`: TTL for in-memory cache (default: 3600 = 1 hour)
   - `EMBEDDING_PROVIDER`: "openai", "local", or "bedrock" (default: "openai", optional if not using Mode B)
   - `EMBEDDING_MODEL`: model name (default: "text-embedding-3-small" for OpenAI)
   - `EMBEDDING_TOP_K`: number of tables to retrieve (default: 5)
   - `EMBEDDING_MAX_DEPTH`: max FK expansion depth (default: 1)
   - `INCLUDE_SCHEMA_SAMPLES`: whether to include sample values in full schema (default: true)
   - `INCLUDE_SCHEMA_WARNINGS`: whether to include one-to-many warnings (default: true)

2. WHEN the Configuration_Manager validates, THE Manager SHALL raise ConfigError if:
   - SCHEMA_RETRIEVAL_MODE is not one of the recognized values
   - EMBEDDING_PROVIDER is set but credentials are missing
   - EMBEDDING_PROVIDER is "openai" but OPENAI_API_KEY is not set

3. WHEN schema retrieval is configured, THE Configuration_Manager SHALL log (but never expose): "Schema retrieval mode: {mode}, Cache TTL: {ttl}s, Embedding provider: {provider}".

### Requirement 10: Caching Performance Tracking

**User Story:** As a performance analyst, I want to measure cache hit/miss rates so that I can evaluate caching effectiveness.

#### Acceptance Criteria

1. WHEN cache operations are performed, THE Cache SHALL track:
   - hit_count: number of successful cache hits (get returns non-expired data)
   - miss_count: number of cache misses (key not found or expired)
   - total_lookups: total get() calls
   - hit_rate: hit_count / total_lookups as float (0.0–1.0)

2. WHEN cache statistics are queried via cache.stats(), THE Cache SHALL return dict:
   ```python
   {
     'hit_count': int,
     'miss_count': int,
     'total_lookups': int,
     'hit_rate': float,
     'avg_cache_size_bytes': int (estimated),
     'evictions': int (number of TTL expirations)
   }
   ```

3. WHEN cache statistics are logged, THE logging SHALL include hit_rate as a percentage (e.g., "Cache hit rate: 87.5%") for easy monitoring.

4. WHEN cache hit rate is below 50%, THE logging SHALL include a warning: "Low cache hit rate; consider increasing TTL or checking cache key consistency".

---

## Acceptance Criteria Summary

**Schema Introspection (Requirement 1):**
- Metadata extracted: table names, columns, types, constraints, descriptions, FKs, row counts
- Sample values for low-cardinality columns (< 20 distinct)
- Errors handled gracefully with descriptive messages

**Caching (Requirement 2):**
- In-memory dict-based cache with thread-safe operations
- TTL expiration enforced
- Cache hit/miss tracking for monitoring

**Mode A – Full Schema (Requirement 3):**
- Human-readable, plain-text format suitable for prompts
- Includes table descriptions, columns, types, samples, FKs
- One-to-many warnings injected

**Mode B – Embedding-Based (Requirement 4):**
- Embeds table descriptions using configurable provider (OpenAI, local, etc.)
- Stores in pgvector for efficient semantic search
- Retrieves top-k relevant tables by similarity
- FK expansion preserves join paths

**Semantic Layer (Requirement 5):**
- Business terms defined in YAML with SQL calculations
- Term detection in questions
- Automatic injection into schema context

**FK Expansion (Requirement 6):**
- Traverses FK relationships to expand table set
- Prevents cycles via visited-set tracking
- Configurable depth (default: 1-hop neighbors)

**One-to-Many Warnings (Requirement 7):**
- Detects one-to-many relationships
- Generates contextual warnings with risk levels
- Warnings appear near affected tables in schema context

**Recall Metric (Requirement 8):**
- Computes recall: (retrieved ∩ expected) / expected
- Computes precision: (retrieved ∩ expected) / retrieved
- Available in eval/metrics.py for evaluation harness

**Configuration (Requirement 9):**
- Environment-driven settings for mode, cache TTL, embedding provider
- Validation with descriptive errors
- Auto-detection of schema size for mode selection

**Performance Tracking (Requirement 10):**
- Cache hit/miss rate monitoring
- Warnings for low hit rates
- Stats available for observability

</content>
