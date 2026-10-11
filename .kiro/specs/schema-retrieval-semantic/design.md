# Design Document: Schema Retrieval and Semantic Layer

## 1. Architecture Overview

### System Diagram

```
┌────────────────────────────────────────────────────────────────────────────┐
│                        LangGraph Agent (planner node)                      │
│                                                                             │
│  Question: "Revenue by customer region for paid orders"                    │
│         ↓                                                                   │
│  Detect semantic terms: ["revenue", "paid"]                                │
│         ↓                                                                   │
│  Schema retrieval needed? YES                                              │
└────────────────────┬──────────────────────────────────────────────────────┘
                     │
        ┌────────────▼───────────────┐
        │   SchemaRetriever          │
        │                            │
        │  1. Check cache            │◄──── SchemaCache (TTL-based)
        │     (hit? → return)        │
        │  2. Determine mode         │
        │     (auto, full, embed)    │
        │  3. Route to Mode A/B      │
        └────────────┬──────────────┘
                     │
        ┌────────────┴────────────────────────┐
        │                                     │
   ┌────▼──────────────────┐     ┌──────────▼────────────────┐
   │  Mode A: Full Schema   │     │  Mode B: Embedding-Based   │
   │  (≤20 tables)          │     │  (>20 tables)              │
   │                        │     │                            │
   │  1. Query all tables   │     │  1. Embed question         │
   │  2. Get metadata       │     │  2. Vector search pgvector │
   │  3. Get FK info        │     │  3. Retrieve top-k tables  │
   │  4. Get samples        │     │  4. Expand via FK          │
   │  5. Format as text     │     │  5. Format retrieved set   │
   │                        │     │                            │
   │  ↓                     │     │  ↓                         │
   │  Full schema text      │     │  Relevant schema text      │
   └────┬──────────────────┘     └──────────┬──────────────┘
        │                                   │
        │  ┌─────────────────────────────────┘
        │  │
        │  ▼
   ┌────────────────────────────────┐
   │  Semantic Layer Injection      │
   │                                │
   │  1. Detect business terms      │
   │     (revenue, active_customer) │
   │  2. Expand schema for missing  │
   │     referenced tables          │
   │  3. Prepend term definitions   │
   │  4. Add one-to-many warnings   │
   │                                │
   │  ↓                             │
   │  Augmented schema context      │
   └────────────────────────────────┘
        │
        ▼
   └──► To LLM (generate_sql node)
        with full schema context ready for SQL generation
```

### Data Flow: Question to Augmented Schema

1. **Question arrives** at retrieve_schema node in LangGraph
2. **Schema decision**: Check cache first (hit? return cached); otherwise determine mode
3. **Mode A (Full Schema)** or **Mode B (Embedding)** retrieves tables
4. **FK Expansion** (Mode B only) automatically includes related tables via FKs
5. **Semantic Layer** detects business terms and injects definitions
6. **One-to-Many Warnings** added for high-risk joins
7. **Augmented schema context** returned to state for LLM prompt construction
8. **LLM (generate_sql node)** uses enriched context to generate SQL

---

## 2. Schema Introspection Design

### Information Schema Queries

**File: `app/tools/schema.py`**

```python
async def get_schema_from_db(target_db_url: str) -> dict[str, Any]:
    """
    Query information_schema to extract all public schema tables.
    
    Returns:
        {
            'customers': {
                'columns': [
                    {'name': 'id', 'type': 'integer', 'nullable': False, 'default': None, 'is_pk': True},
                    {'name': 'name', 'type': 'character varying', 'nullable': False, ...}
                ],
                'pk_columns': ['id'],
                'row_count': 500,
                'description': 'Base customer dimension...',
                'indexes': ['idx_customers_email'],
                'fk_relationships': []  # FKs referencing this table
            },
            'orders': {...},
            ...
        }
    """
    async with await psycopg.AsyncConnection.connect(target_db_url) as conn:
        async with conn.cursor() as cur:
            # Step 1: Get tables
            await cur.execute("""
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
                ORDER BY table_name
            """)
            tables = [row[0] for row in await cur.fetchall()]
            
            schema = {}
            for table_name in tables:
                schema[table_name] = await _get_table_metadata(cur, table_name)
            
            return schema

async def _get_table_metadata(cur, table_name: str) -> dict[str, Any]:
    """Extract detailed metadata for a single table."""
    
    # Columns
    await cur.execute("""
        SELECT column_name, data_type, is_nullable, column_default
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = %s
        ORDER BY ordinal_position
    """, (table_name,))
    columns = []
    for col_name, data_type, is_nullable, col_default in await cur.fetchall():
        columns.append({
            'name': col_name,
            'type': data_type,
            'nullable': is_nullable == 'YES',
            'default': col_default
        })
    
    # Primary keys
    await cur.execute("""
        SELECT column_name
        FROM information_schema.key_column_usage
        WHERE table_schema = 'public' AND table_name = %s 
          AND constraint_type = 'PRIMARY KEY'
    """, (table_name,))
    pk_columns = [row[0] for row in await cur.fetchall()]
    
    # Mark PK columns
    for col in columns:
        if col['name'] in pk_columns:
            col['is_pk'] = True
    
    # Row count (estimated)
    await cur.execute("""
        SELECT n_live_tup FROM pg_stat_user_tables WHERE relname = %s
    """, (table_name,))
    row_count_result = await cur.fetchone()
    row_count = row_count_result[0] if row_count_result else 0
    
    # Description (comments)
    await cur.execute("""
        SELECT description FROM pg_description
        WHERE objoid = (SELECT oid FROM pg_class WHERE relname = %s AND relnamespace = (SELECT oid FROM pg_namespace WHERE nspname = 'public'))
          AND objsubid = 0
    """, (table_name,))
    desc_result = await cur.fetchone()
    description = desc_result[0] if desc_result else None
    
    # Indexes
    await cur.execute("""
        SELECT indexname FROM pg_indexes
        WHERE tablename = %s AND schemaname = 'public'
    """, (table_name,))
    indexes = [row[0] for row in await cur.fetchall()]
    
    # Sample values for low-cardinality columns
    sampled_values = await _get_sample_values(cur, table_name, columns)
    
    return {
        'columns': columns,
        'pk_columns': pk_columns,
        'row_count': row_count,
        'description': description,
        'indexes': indexes,
        'fk_relationships': [],  # Will be populated separately
        'sampled_values': sampled_values
    }

async def _get_sample_values(cur, table_name: str, columns: list) -> dict[str, list]:
    """Get distinct sample values for low-cardinality columns."""
    sampled_values = {}
    for col in columns:
        # Only for string/enum-like columns
        if col['type'] in ('character varying', 'character', 'text', 'integer'):
            try:
                await cur.execute(f"""
                    SELECT DISTINCT {col['name']}
                    FROM {table_name}
                    ORDER BY {col['name']}
                    LIMIT 20
                """)
                distinct_vals = [row[0] for row in await cur.fetchall()]
                if len(distinct_vals) <= 20:  # Low cardinality
                    sampled_values[col['name']] = distinct_vals
            except Exception:
                pass  # Skip columns that fail
    return sampled_values

async def get_fk_relationships(target_db_url: str) -> list[dict]:
    """
    Extract all foreign key relationships.
    
    Returns:
        [
            {
                'parent_table': 'customers',
                'parent_column': 'id',
                'child_table': 'orders',
                'child_column': 'customer_id',
                'constraint_name': 'fk_orders_customer'
            },
            ...
        ]
    """
    async with await psycopg.AsyncConnection.connect(target_db_url) as conn:
        async with conn.cursor() as cur:
            await cur.execute("""
                SELECT
                    tc.table_name as child_table,
                    kcu.column_name as child_column,
                    ccu.table_name as parent_table,
                    ccu.column_name as parent_column,
                    tc.constraint_name
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu ON tc.constraint_name = kcu.constraint_name
                JOIN information_schema.constraint_column_usage ccu ON ccu.constraint_name = tc.constraint_name
                WHERE tc.table_schema = 'public' AND tc.constraint_type = 'FOREIGN KEY'
            """)
            fks = []
            for child_table, child_col, parent_table, parent_col, constraint_name in await cur.fetchall():
                fks.append({
                    'parent_table': parent_table,
                    'parent_column': parent_col,
                    'child_table': child_table,
                    'child_column': child_col,
                    'constraint_name': constraint_name
                })
            return fks
```

### Metadata Structure

Schema dict structure (returned from `get_schema_from_db()`):

```python
{
    'table_name': {
        'columns': [
            {'name': 'id', 'type': 'integer', 'nullable': False, 'default': None, 'is_pk': True},
            {'name': 'email', 'type': 'character varying', 'nullable': False, 'default': None, 'is_pk': False},
        ],
        'pk_columns': ['id'],
        'row_count': 500,
        'description': 'Base customer dimension; one row per unique customer.',
        'indexes': ['idx_customers_email', 'idx_customers_created_at'],
        'fk_relationships': [
            {'parent_table': None, 'parent_column': None, 'child_table': 'orders', 'child_column': 'customer_id'}
        ],
        'sampled_values': {
            'state': ['CA', 'NY', 'TX', 'FL', 'PA'],
            'region': ['West', 'Northeast', 'South', 'Midwest']
        }
    }
}
```

---

## 3. Caching Strategy

### In-Memory Cache Implementation

**File: `app/tools/schema_cache.py`**

```python
import threading
import time
from typing import Optional, Any, Dict

class SchemaCache:
    """Thread-safe in-memory cache with TTL expiration."""
    
    def __init__(self):
        self._cache: Dict[str, tuple[Any, float]] = {}  # {key: (value, timestamp)}
        self._lock = threading.Lock()
        self._stats = {'hits': 0, 'misses': 0, 'evictions': 0}
    
    def get(self, key: str, ttl_seconds: int = 3600) -> Optional[Any]:
        """Get cached value if exists and not expired."""
        with self._lock:
            if key not in self._cache:
                self._stats['misses'] += 1
                return None
            
            value, timestamp = self._cache[key]
            age = time.time() - timestamp
            
            if age > ttl_seconds:
                # Expired
                del self._cache[key]
                self._stats['evictions'] += 1
                self._stats['misses'] += 1
                return None
            
            self._stats['hits'] += 1
            return value
    
    def set(self, key: str, value: Any) -> None:
        """Store value in cache."""
        with self._lock:
            self._cache[key] = (value, time.time())
    
    def invalidate(self, key: str) -> None:
        """Remove entry from cache."""
        with self._lock:
            if key in self._cache:
                del self._cache[key]
    
    def clear(self) -> None:
        """Clear all cache entries."""
        with self._lock:
            self._cache.clear()
            self._stats = {'hits': 0, 'misses': 0, 'evictions': 0}
    
    def stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        with self._lock:
            total = self._stats['hits'] + self._stats['misses']
            hit_rate = self._stats['hits'] / total if total > 0 else 0
            return {
                'hits': self._stats['hits'],
                'misses': self._stats['misses'],
                'total': total,
                'hit_rate': hit_rate,
                'evictions': self._stats['evictions'],
                'size': len(self._cache)
            }
```

### Cache Key Design

```python
CACHE_KEY_SCHEMA = "schema_{database_name}_{mode}"
# Example: "schema_querypilot_target_full" or "schema_querypilot_target_embedding"

CACHE_KEY_EMBEDDINGS = "embeddings_{database_name}"
# Example: "embeddings_querypilot_target"
```

---

## 4. Mode A: Full Schema Formatting

### Human-Readable Schema Formatter

**File: `app/tools/schema_formatter.py`**

```python
def format_full_schema(
    schema_dict: Dict[str, Any],
    fk_relationships: List[Dict],
    include_samples: bool = True,
    include_warnings: bool = True,
    include_row_counts: bool = True
) -> str:
    """
    Format schema as human-readable text for LLM consumption.
    """
    lines = ["TABLES:\n"]
    
    # Detect one-to-many joins for warnings
    one_to_many_warnings = (
        detect_one_to_many_joins(schema_dict) if include_warnings else []
    )
    
    for table_num, (table_name, table_info) in enumerate(schema_dict.items(), 1):
        # Table header
        row_count_str = f" ({table_info['row_count']} rows)" if include_row_counts else ""
        lines.append(f"{table_num}. {table_name}{row_count_str}")
        
        # Description
        if table_info.get('description'):
            lines.append(f"   Description: {table_info['description']}")
        
        # Columns
        lines.append("   Columns:")
        for col in table_info['columns']:
            col_str = f"     - {col['name']} {col['type']}"
            if col.get('is_pk'):
                col_str += " PRIMARY KEY"
            if not col['nullable']:
                col_str += " NOT NULL"
            
            # Add sample values
            if include_samples and col['name'] in table_info.get('sampled_values', {}):
                samples = table_info['sampled_values'][col['name']][:5]
                samples_str = ', '.join(repr(s) for s in samples)
                col_str += f", samples: [{samples_str}]"
            
            lines.append(col_str)
        
        # Foreign keys
        table_fks = [fk for fk in fk_relationships if fk['child_table'] == table_name]
        if table_fks:
            lines.append("   Foreign Keys:")
            for fk in table_fks:
                fk_str = f"     - {fk['child_table']}.{fk['child_column']} → {fk['parent_table']}.{fk['parent_column']}"
                lines.append(fk_str)
        else:
            lines.append("   Foreign Keys: none")
        
        # Indexes
        if table_info.get('indexes'):
            index_str = ", ".join(table_info['indexes'])
            lines.append(f"   Indexes: {index_str}")
        
        # One-to-many warnings for this table
        if include_warnings:
            for parent, child, risk_level in one_to_many_warnings:
                if parent == table_name:
                    warning = f"   ⚠️  {parent} → {child} is one-to-many. SUM/COUNT will multiply if not grouped carefully."
                    if risk_level == 'high':
                        warning = f"   ⚠️ HIGH RISK: {warning}"
                    lines.append(warning)
        
        lines.append("")  # Blank line between tables
    
    return "\n".join(lines)
```

### Example Output

```
TABLES:

1. customers (500 rows)
   Description: Base customer dimension; one row per unique customer.
   Columns:
     - id integer PRIMARY KEY
     - name character varying NOT NULL, samples: ['Alice Smith', 'Bob Johnson', 'Carol Davis', 'Diana Lee', 'Edward Martinez']
     - email character varying NOT NULL UNIQUE
     - state character varying, samples: ['CA', 'NY', 'TX', 'FL', 'PA']
     - region character varying, samples: ['West', 'Northeast', 'South', 'Midwest']
     - created_at timestamp DEFAULT CURRENT_TIMESTAMP
   Foreign Keys: none
   Indexes: idx_customers_email, idx_customers_created_at

2. orders (5000 rows)
   Description: Order transactions; one row per customer order. Time-series fact table.
   Columns:
     - id integer PRIMARY KEY
     - customer_id integer NOT NULL, references customers.id
     - order_date date NOT NULL
     - status character varying NOT NULL, samples: ['paid', 'refunded', 'cancelled']
     - total_amount numeric(10,2) NOT NULL
   Foreign Keys:
     - orders.customer_id → customers.id
   Indexes: idx_orders_customer_id, idx_orders_order_date
   ⚠️ orders → order_items is one-to-many. SUM/COUNT will multiply if not grouped carefully.
```

---

## 5. Mode B: Embedding-Based Retrieval

### Embedding Provider Interface

**File: `app/tools/embeddings.py`**

```python
from abc import ABC, abstractmethod
from typing import List, Tuple

class EmbeddingProvider(ABC):
    """Abstract interface for embedding providers."""
    
    @abstractmethod
    async def embed(self, text: str) -> List[float]:
        """Embed text into vector."""
        pass

class OpenAIEmbeddings(EmbeddingProvider):
    """OpenAI embeddings provider."""
    
    def __init__(self, api_key: str, model: str = "text-embedding-3-small"):
        self.client = openai.AsyncOpenAI(api_key=api_key)
        self.model = model
    
    async def embed(self, text: str) -> List[float]:
        response = await self.client.embeddings.create(
            model=self.model,
            input=text
        )
        return response.data[0].embedding

class LocalEmbeddings(EmbeddingProvider):
    """Local embeddings using sentence-transformers."""
    
    def __init__(self, model: str = "all-MiniLM-L6-v2"):
        from sentence_transformers import SentenceTransformer
        self.model_instance = SentenceTransformer(model)
    
    async def embed(self, text: str) -> List[float]:
        embeddings = self.model_instance.encode([text])
        return embeddings[0].tolist()
```

### pgvector Storage and Retrieval

**File: `app/tools/schema_embeddings.py`**

```python
async def store_table_embeddings(
    schema_dict: Dict[str, Any],
    embedding_provider: EmbeddingProvider,
    target_db_url: str,
    vector_dimension: int = 1536
) -> int:
    """
    Embed each table description and store in pgvector table.
    """
    # Create table if not exists
    async with await psycopg.AsyncConnection.connect(target_db_url) as conn:
        async with conn.cursor() as cur:
            # Ensure pgvector extension
            await cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
            
            # Create table
            await cur.execute(f"""
                CREATE TABLE IF NOT EXISTS table_embeddings (
                    table_name TEXT PRIMARY KEY,
                    description TEXT,
                    embedding vector({vector_dimension}),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Create index for efficient search
            await cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_table_embeddings_embedding
                ON table_embeddings USING ivfflat (embedding vector_cosine_ops)
                WITH (lists = 100)
            """)
            
            conn.commit()
    
    # Embed and insert
    stored_count = 0
    async with await psycopg.AsyncConnection.connect(target_db_url) as conn:
        async with conn.cursor() as cur:
            for table_name, table_info in schema_dict.items():
                # Create description: name + columns
                columns_str = ", ".join([col['name'] for col in table_info['columns']])
                description = f"{table_name}: {table_info.get('description', table_name)}. Columns: {columns_str}"
                
                # Embed
                embedding = await embedding_provider.embed(description)
                
                # Insert or update
                await cur.execute("""
                    INSERT INTO table_embeddings (table_name, description, embedding)
                    VALUES (%s, %s, %s::vector)
                    ON CONFLICT (table_name) DO UPDATE SET embedding = EXCLUDED.embedding
                """, (table_name, description, embedding))
                
                stored_count += 1
            
            conn.commit()
    
    return stored_count

async def retrieve_tables_by_embedding(
    question: str,
    embedding_provider: EmbeddingProvider,
    target_db_url: str,
    top_k: int = 5
) -> List[str]:
    """
    Embed question and retrieve top-k similar tables.
    """
    # Embed question
    question_embedding = await embedding_provider.embed(question)
    
    # Search pgvector
    async with await psycopg.AsyncConnection.connect(target_db_url) as conn:
        async with conn.cursor() as cur:
            await cur.execute(f"""
                SELECT table_name
                FROM table_embeddings
                ORDER BY embedding <-> %s::vector
                LIMIT %s
            """, (question_embedding, top_k))
            
            tables = [row[0] for row in await cur.fetchall()]
    
    return tables
```

### FK Expansion Algorithm

**File: `app/tools/fk_expansion.py`**

```python
def expand_schema_via_fk(
    initial_tables: Set[str],
    fk_relationships: List[Dict],
    schema_dict: Dict[str, Any],
    max_depth: int = 1
) -> Tuple[Set[str], Dict[str, Any]]:
    """
    Expand table set via FK relationships using BFS with depth limit and cycle prevention.
    
    Args:
        initial_tables: Set of table names to expand from
        fk_relationships: List of FK dicts with parent/child info
        schema_dict: Full schema dict for validation
        max_depth: Max traversal depth (1 = direct neighbors only)
    
    Returns:
        (expanded_tables, join_paths_info)
    """
    expanded = set(initial_tables)
    visited = set()
    queue = [(table, 0) for table in initial_tables]  # (table, depth)
    join_paths = defaultdict(list)
    
    while queue:
        current_table, depth = queue.pop(0)
        
        if current_table in visited or depth >= max_depth:
            continue
        
        visited.add(current_table)
        
        # Find FKs where current_table is parent
        for fk in fk_relationships:
            if fk['parent_table'] == current_table:
                child_table = fk['child_table']
                if child_table not in expanded:
                    expanded.add(child_table)
                    join_paths[current_table].append({
                        'target': child_table,
                        'type': 'has_many',
                        'fk': f"{child_table}.{fk['child_column']} → {fk['parent_table']}.{fk['parent_column']}"
                    })
                    queue.append((child_table, depth + 1))
        
        # Find FKs where current_table is child
        for fk in fk_relationships:
            if fk['child_table'] == current_table:
                parent_table = fk['parent_table']
                if parent_table not in expanded:
                    expanded.add(parent_table)
                    join_paths[current_table].append({
                        'target': parent_table,
                        'type': 'belongs_to',
                        'fk': f"{fk['child_table']}.{fk['child_column']} → {fk['parent_table']}.{fk['parent_column']}"
                    })
                    queue.append((parent_table, depth + 1))
    
    return expanded, dict(join_paths)
```

---

## 6. Semantic Layer Design

### YAML Structure

**File: `app/semantic_layer.yaml`**

```yaml
business_terms:
  revenue:
    description: "Total revenue from paid orders only. Calculated as SUM of order totals where status='paid'."
    calculation_sql: "SUM(orders.total_amount) FILTER (WHERE orders.status = 'paid')"
    referenced_tables: ["orders"]
    alternative_names: ["total_revenue", "sales", "gross_revenue"]
    
  order_count:
    description: "Count of all orders, including paid, refunded, and cancelled orders."
    calculation_sql: "COUNT(DISTINCT orders.id)"
    referenced_tables: ["orders"]
    alternative_names: ["total_orders", "order_volume"]
    
  average_order_value:
    description: "Average order value for paid orders only."
    calculation_sql: "AVG(orders.total_amount) FILTER (WHERE orders.status = 'paid')"
    referenced_tables: ["orders"]
    alternative_names: ["avg_order_value", "mean_order_total"]
    
  active_customer:
    description: "Customer with at least one paid order in the last 90 days."
    calculation_sql: "EXISTS (SELECT 1 FROM orders WHERE orders.customer_id = customers.id AND orders.status = 'paid' AND orders.order_date >= CURRENT_DATE - INTERVAL '90 days')"
    referenced_tables: ["customers", "orders"]
    alternative_names: ["active_user", "engaged_customer"]
    
  yoy_growth:
    description: "Year-over-year growth rate comparing current year to prior year."
    calculation_sql: "(current_year_value - prior_year_value) / prior_year_value * 100"
    referenced_tables: ["orders"]
    alternative_names: ["yoy_change", "year_over_year"]
```

### Semantic Layer Loader

**File: `app/tools/semantic_layer.py`**

```python
import yaml
from typing import Dict, List, Set

class SemanticLayerLoader:
    """Load and manage business term definitions."""
    
    def __init__(self, yaml_path: str):
        with open(yaml_path, 'r') as f:
            self.config = yaml.safe_load(f)
        self.terms = self.config.get('business_terms', {})
        # Build reverse index: synonym → term_name
        self.synonym_index = {}
        for term_name, term_info in self.terms.items():
            self.synonym_index[term_name.lower()] = term_name
            for alt_name in term_info.get('alternative_names', []):
                self.synonym_index[alt_name.lower()] = term_name
    
    def detect_terms(self, question: str) -> List[str]:
        """Detect which business terms are mentioned in the question."""
        question_lower = question.lower()
        detected = set()
        
        for synonym, term_name in self.synonym_index.items():
            # Simple word boundary check (not perfect, but good enough)
            import re
            if re.search(r'\b' + re.escape(synonym) + r'\b', question_lower):
                detected.add(term_name)
        
        return list(detected)
    
    def get_term_definition(self, term_name: str) -> Dict:
        """Get definition for a term."""
        return self.terms.get(term_name, {})
    
    def get_referenced_tables(self, term_name: str) -> Set[str]:
        """Get tables referenced by a term."""
        term_info = self.terms.get(term_name, {})
        return set(term_info.get('referenced_tables', []))

def inject_semantic_terms(
    schema_context: str,
    detected_terms: List[str],
    semantic_loader: SemanticLayerLoader
) -> str:
    """Prepend business term definitions to schema context."""
    if not detected_terms:
        return schema_context
    
    lines = ["BUSINESS TERMS:\n"]
    for term in detected_terms:
        term_info = semantic_loader.get_term_definition(term)
        if term_info:
            description = term_info.get('description', term)
            calculation = term_info.get('calculation_sql', 'N/A')
            lines.append(f"- {term}: {description}")
            lines.append(f"  Calculation: {calculation}\n")
    
    lines.append("TABLES:\n")
    return "".join(lines) + schema_context
```

---

## 7. One-to-Many Detection and Warnings

### Detection Algorithm

**File: `app/tools/join_warnings.py`**

```python
def detect_one_to_many_joins(
    schema_dict: Dict[str, Any],
    fk_relationships: List[Dict]
) -> List[Tuple[str, str, str]]:
    """
    Detect one-to-many relationships.
    
    Returns:
        [(parent_table, child_table, risk_level), ...]
        where risk_level is "low", "medium", or "high"
    """
    one_to_many = []
    
    for fk in fk_relationships:
        parent_table = fk['parent_table']
        child_table = fk['child_table']
        
        parent_rows = schema_dict.get(parent_table, {}).get('row_count', 1)
        child_rows = schema_dict.get(child_table, {}).get('row_count', 1)
        
        if parent_rows == 0:
            continue
        
        avg_children_per_parent = child_rows / parent_rows
        
        if avg_children_per_parent > 1.1:  # One-to-many detected
            if avg_children_per_parent < 2:
                risk_level = "low"
            elif avg_children_per_parent < 10:
                risk_level = "medium"
            else:
                risk_level = "high"
            
            one_to_many.append((parent_table, child_table, risk_level))
    
    return one_to_many
```

### Warning Message Generation

```python
def generate_join_warnings(one_to_many: List[Tuple[str, str, str]]) -> Dict[str, str]:
    """
    Generate warning messages for one-to-many relationships.
    
    Returns:
        {parent_table: "warning message"}
    """
    warnings = {}
    
    for parent_table, child_table, risk_level in one_to_many:
        if parent_table not in warnings:
            warnings[parent_table] = []
        
        if risk_level == "high":
            msg = f"⚠️ HIGH RISK: {parent_table} → {child_table} is one-to-many. SUM/COUNT will multiply. Use DISTINCT or GROUP BY carefully."
        else:
            msg = f"⚠️ {parent_table} → {child_table} is one-to-many ({risk_level} risk). Aggregate functions may double-count."
        
        warnings[parent_table].append(msg)
    
    return warnings
```

---

## 8. Schema Retrieval Recall Metric

### Metric Computation

**File: `eval/metrics.py` (schema retrieval functions)**

```python
def compute_schema_retrieval_recall(
    retrieved_tables: Set[str],
    expected_tables: Set[str]
) -> Dict[str, float]:
    """
    Compute recall and precision for schema retrieval.
    
    Args:
        retrieved_tables: Tables returned by schema retrieval system
        expected_tables: Tables needed to generate correct SQL
    
    Returns:
        {
            'recall': float (0-1),
            'precision': float (0-1),
            'retrieved_count': int,
            'expected_count': int,
            'common_count': int
        }
    """
    if len(expected_tables) == 0:
        # Perfect recall for empty requirements
        return {
            'recall': 1.0,
            'precision': 1.0 if len(retrieved_tables) == 0 else 0.0,
            'retrieved_count': len(retrieved_tables),
            'expected_count': 0,
            'common_count': 0
        }
    
    common = retrieved_tables & expected_tables
    recall = len(common) / len(expected_tables)
    precision = len(common) / len(retrieved_tables) if len(retrieved_tables) > 0 else 0.0
    
    return {
        'recall': recall,
        'precision': precision,
        'retrieved_count': len(retrieved_tables),
        'expected_count': len(expected_tables),
        'common_count': len(common),
        'missing_tables': list(expected_tables - retrieved_tables),
        'over_retrieved_tables': list(retrieved_tables - expected_tables)
    }
```

---

## 9. Configuration Integration

### Settings Extension

**File: `app/config.py` (additions to existing Config)**

```python
class Config(BaseSettings):
    # ... existing fields ...
    
    # Schema Retrieval
    schema_retrieval_mode: str = "auto"  # full, embedding, auto
    schema_retrieval_full_table_limit: int = 20  # Threshold for mode selection
    schema_cache_ttl_seconds: int = 3600  # 1 hour default
    
    # Embedding
    embedding_provider: Optional[str] = None  # openai, local, bedrock
    embedding_model: str = "text-embedding-3-small"
    embedding_top_k: int = 5
    embedding_max_depth: int = 1  # FK expansion depth
    
    # Schema Formatting
    include_schema_samples: bool = True
    include_schema_warnings: bool = True
    include_row_counts: bool = True
    
    class ConfigDict:
        env_file = ".env"
        env_file_encoding = "utf-8"
```

---

## 10. Error Handling

### Custom Exception Types

**File: `app/tools/exceptions.py` (additions)**

```python
class SchemaError(Exception):
    """Schema retrieval or introspection error."""
    pass

class EmbeddingError(Exception):
    """Embedding computation or storage error."""
    pass

class ConfigError(Exception):
    """Configuration validation error."""
    pass

class CacheError(Exception):
    """Cache operation error."""
    pass
```

### Fallback Strategies

| Error Scenario | Fallback Action |
|---|---|
| Mode B embedding fails | Fall back to Mode A (full schema) if configured, else raise error |
| pgvector extension missing | Raise ConfigError with install instructions |
| Embedding provider API timeout | Raise EmbeddingError; consider retrying or using local embeddings |
| Cache corrupted | Clear cache and re-fetch from DB |
| FK metadata incomplete | Log warning and continue with partial FK expansion |

---

## 11. Decisions and Rationale

### Why Two Modes (Full vs. Embedding-Based)?

**Decision:** Provide Mode A (full schema) for small schemas and Mode B (embedding-based) for large schemas.

**Rationale:**
- Small schemas (≤20 tables) are small enough to fit entirely in LLM context without overwhelming it.
- Full schema maximizes information availability and eliminates retrieval errors for small DBs.
- Large schemas (>20 tables) create token bloat if included fully; semantic search over embeddings intelligently selects only relevant tables.
- Auto-detection based on table count provides transparent switching without user intervention.

### Why pgvector for Embedding Storage?

**Decision:** Use PostgreSQL with pgvector extension instead of external vector database.

**Rationale:**
- Keeps the entire stack within PostgreSQL, reducing operational complexity.
- pgvector integrates seamlessly with existing DB connections.
- Embeddings are co-located with schema metadata for efficient queries.
- HNSW/IVFFLAT indexes provide fast semantic search.
- Embeddings can be invalidated and recomputed without external service calls.

### Why FK Expansion?

**Decision:** Automatically expand retrieved table set via FK relationships.

**Rationale:**
- Join paths are deterministic and derivable from schema; no guessing needed.
- LLM often needs multiple related tables to generate correct SQL.
- Automatic expansion prevents missing required tables without explicit retrieval.
- Configurable depth (e.g., 1-hop = direct neighbors) balances completeness and conciseness.

### Why Semantic Layer?

**Decision:** Define business terms in YAML and inject definitions into schema context.

**Rationale:**
- Resolves ambiguity without LLM guessing (e.g., "revenue" could mean gross, net, or paid-only).
- SQL calculations are explicit and maintainable in one place.
- Semantic term detection in questions is simple (regex-based word matching).
- Updates to term definitions don't require retraining or prompt tuning.

### Why One-to-Many Warnings?

**Decision:** Detect and warn about one-to-many relationships to prevent double-counting bugs.

**Rationale:**
- One-to-many joins are a common source of data quality bugs (e.g., SUM(revenue) × order_count).
- Warnings are low-friction: injected into schema context contextually.
- Risk levels (low/medium/high) help LLM prioritize attention.
- Warnings reduce need for fix/retry loop by preventing the error upfront.

---

## 12. Data Structures and Algorithms Summary

| Component | Algorithm | Complexity |
|---|---|---|
| Schema introspection | Query information_schema | O(T × C) where T=tables, C=cols |
| FK expansion | BFS with depth limit | O(T + E) where E=FK edges |
| One-to-many detection | Scan schema, compute ratios | O(T) |
| Semantic term detection | Regex word matching | O(W × T) where W=words, T=terms |
| Embedding retrieval | pgvector HNSW search | O(log n) with HNSW index |
| Cache lookup | Dict get + TTL check | O(1) amortized |

---

## 13. Integration with LangGraph Agent

### Flow in retrieve_schema Node

```python
async def retrieve_schema(state: AgentState, config: Config) -> dict:
    """Retrieve and format schema context for LLM."""
    
    # 1. Check cache
    cache_key = f"schema_{get_db_name(config.target_db_url)}"
    cached_schema = schema_cache.get(cache_key, ttl_seconds=config.schema_cache_ttl_seconds)
    if cached_schema:
        return {"schema_context": cached_schema}
    
    # 2. Get full schema from DB
    schema_dict = await get_schema_from_db(config.target_db_url)
    fk_relationships = await get_fk_relationships(config.target_db_url)
    
    # 3. Determine mode
    table_count = len(schema_dict)
    if config.schema_retrieval_mode == "auto":
        mode = "full" if table_count <= 20 else "embedding"
    else:
        mode = config.schema_retrieval_mode
    
    # 4. Retrieve and format schema
    if mode == "full":
        schema_context = format_full_schema(
            schema_dict, fk_relationships,
            include_samples=config.include_schema_samples,
            include_warnings=config.include_schema_warnings
        )
    else:  # Mode B: embedding-based
        retrieved_tables = await retrieve_tables_by_embedding(
            state["question"],
            embedding_provider=config.embedding_provider,
            target_db_url=config.target_db_url,
            top_k=config.embedding_top_k
        )
        expanded_tables, _ = expand_schema_via_fk(
            set(retrieved_tables),
            fk_relationships,
            schema_dict,
            max_depth=config.embedding_max_depth
        )
        filtered_schema = {t: schema_dict[t] for t in expanded_tables}
        schema_context = format_full_schema(
            filtered_schema, fk_relationships,
            include_samples=config.include_schema_samples,
            include_warnings=config.include_schema_warnings
        )
    
    # 5. Inject semantic layer
    semantic_loader = SemanticLayerLoader(config.semantic_layer_yaml_path)
    detected_terms = semantic_loader.detect_terms(state["question"])
    for term in detected_terms:
        # Auto-expand schema to include term's referenced tables
        term_tables = semantic_loader.get_referenced_tables(term)
        for table in term_tables:
            if table in schema_dict and table not in filtered_schema:
                filtered_schema[table] = schema_dict[table]
    
    schema_context = inject_semantic_terms(schema_context, detected_terms, semantic_loader)
    
    # 6. Cache result
    schema_cache.set(cache_key, schema_context)
    
    return {"schema_context": schema_context}
```

</content>
