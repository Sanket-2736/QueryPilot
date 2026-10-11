# Design Document: Seed DB and Baseline Text-to-SQL

## 1. Architecture Overview

### System Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          Local Development Environment                       │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                               │
│  docker-compose (up/down)                                                    │
│  ├─ target_db (PostgreSQL 16)              ├─ app_db (PostgreSQL 16)        │
│  │  ├─ schema.sql (DDL)                    │  ├─ app_schema.sql             │
│  │  ├─ generator.py (synthetic data)       │  ├─ conversations table        │
│  │  ├─ 5 tables (customers, products,      │  ├─ query_log table           │
│  │  │  orders, order_items, reviews)       │  └─ eval_runs table           │
│  │  ├─ querypilot_ro (read-only role)      │                               │
│  │  └─ Health check: pg_isready             │  Health check: pg_isready    │
│  │     (5s interval)                        │     (5s interval)             │
│  │                                          │                               │
│  │ Port: 5433                              │ Port: 5432                    │
│  │ Target DB URL: (env var)                │ App DB URL: (env var)         │
│  └──────────────┬──────────────────────────┴─────────────────────────────┘
│                 │                                                           │
│         ┌───────┴────────┐                                                  │
│         │                │                                                  │
│    ┌────▼──────────┐  ┌──▼────────────────┐                                │
│    │ Verification  │  │ Baseline Runner   │                                │
│    ├───────────────┤  ├───────────────────┤                                │
│    │ seed.verify   │  │ eval.run_eval     │                                │
│    │ ├─ Schema OK? │  │ ├─ Load dataset   │                                │
│    │ ├─ Data OK?   │  │ ├─ For each item: │                                │
│    │ ├─ Role OK?   │  │ │  1. Question    │                                │
│    │ ├─ FK OK?     │  │ │  2. LLM Client  │                                │
│    │ └─ Exit 0/1   │  │ │  3. Generate SQL│                                │
│    └───────────────┘  │ │  4. Execute     │                                │
│                       │ │  5. Compare     │                                │
│    ┌─────────────────┤ │  6. Log result  │                                │
│    │ app.verify_llm  │ ├───────────────────┤                                │
│    │ ├─ Provider OK? │ │ Output:           │                                │
│    │ ├─ Creds OK?    │ │ ├─ Accuracy %     │                                │
│    │ ├─ Test call    │ │ ├─ By category    │                                │
│    │ └─ Exit 0/1     │ │ ├─ Error rate     │                                │
│    └─────────────────┤ │ └─ JSON report    │                                │
│                       └──▼──────────────────┘                                │
│                          │                                                   │
│                    ┌─────▼──────────┐                                        │
│                    │   LLM Client   │                                        │
│                    ├────────────────┤                                        │
│                    │ Abstract:      │                                        │
│                    │ call(prompt)   │                                        │
│                    │                │                                        │
│                    │ Concrete:      │                                        │
│                    │ ├─ OpenAI      │◄──── API calls (env-configured)       │
│                    │ ├─ Anthropic   │                                        │
│                    │ └─ Bedrock     │                                        │
│                    └────────────────┘                                        │
│                                                                               │
│  Config Layer (pydantic BaseSettings)                                        │
│  ├─ .env file                                                               │
│  └─ Environment variables                                                   │
│      ├─ DATABASE: TARGET_DB_URL, APP_DB_URL, TARGET_DB_READONLY_ROLE      │
│      ├─ LLM: LLM_PROVIDER, LLM_MODEL, provider-specific keys              │
│      └─ EXECUTION: QUERY_TIMEOUT_SECONDS, RESULT_ROW_LIMIT                │
│                                                                               │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Component Interactions and Data Flow

**Initialization Flow (docker-compose up):**
1. docker-compose starts target_db service
2. target_db runs init script: load schema.sql (creates 5 tables + querypilot_ro role)
3. target_db runs post-init: python seed/generator.py (generates 500 customers, ~5k orders, etc.)
4. Health check: pg_isready polls target_db until ready (5s timeout, retries)
5. docker-compose starts app_db service (same pattern with app_schema.sql)
6. Both services healthy → docker-compose up completes

**Baseline Evaluation Flow (eval.run_eval --baseline):**
1. Load configuration from .env (TARGET_DB_URL, LLM_PROVIDER, LLM_MODEL, etc.)
2. Load eval/dataset.jsonl (20 items)
3. For each item:
   a. Extract question from item
   b. Retrieve full schema from Target DB (SELECT from information_schema)
   c. Construct prompt: schema + context + question
   d. Call LLMClient (instantiated based on LLM_PROVIDER env var)
   e. Extract SQL from LLM response (markdown cleanup)
   f. Execute generated SQL against Target DB (5s timeout, 1000 row limit, querypilot_ro role)
   g. Execute gold_sql against Target DB
   h. Compare result sets (order-insensitive)
   i. Log item result: question, generated_sql, gold_sql, match (true/false), error (if any)
4. Compute metrics:
   - Overall accuracy: (matches) / 20
   - Category breakdown: accuracy per category
   - Error rate: (SQL errors) / 20
5. Log full run to App DB (eval_runs table)
6. Print summary to stdout + save detailed report to eval/baseline_results.json

---

## 2. Database Schema Design

### DDL Structure

**File: `seed/schema.sql`**

```sql
-- Customers table: base customer dimension
CREATE TABLE customers (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    email VARCHAR(255) NOT NULL UNIQUE,
    state VARCHAR(2) NOT NULL,  -- e.g., "CA", "NY", "TX"
    region VARCHAR(50) NOT NULL,  -- derived from state: "West", "Northeast", "South", "Midwest"
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

COMMENT ON TABLE customers IS 'Base customer dimension; one row per unique customer.';
COMMENT ON COLUMN customers.id IS 'Unique customer identifier.';
COMMENT ON COLUMN customers.name IS 'Full name of customer (synthetic, no PII).';
COMMENT ON COLUMN customers.email IS 'Unique email address (synthetic).';
COMMENT ON COLUMN customers.state IS 'Two-letter US state code.';
COMMENT ON COLUMN customers.region IS 'Geographic region derived from state.';
COMMENT ON COLUMN customers.created_at IS 'System timestamp when customer was created (2024).';

-- Products table: product catalog
CREATE TABLE products (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    category VARCHAR(100) NOT NULL,  -- e.g., "Electronics", "Apparel", "Home", "Books", "Sports"
    price DECIMAL(10, 2) NOT NULL,
    stock_quantity INT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

COMMENT ON TABLE products IS 'Product catalog; one row per unique product SKU.';
COMMENT ON COLUMN products.id IS 'Unique product identifier.';
COMMENT ON COLUMN products.name IS 'Product name.';
COMMENT ON COLUMN products.category IS 'Product category for segmentation.';
COMMENT ON COLUMN products.price IS 'List price in USD.';
COMMENT ON COLUMN products.stock_quantity IS 'Current inventory count.';
COMMENT ON COLUMN products.created_at IS 'System timestamp when product was added to catalog.';

-- Orders table: transaction fact table
CREATE TABLE orders (
    id SERIAL PRIMARY KEY,
    customer_id INT NOT NULL REFERENCES customers(id) ON DELETE RESTRICT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    order_date DATE NOT NULL,  -- Separate from created_at; transaction date for time-series analysis
    status VARCHAR(50) NOT NULL CHECK (status IN ('paid', 'refunded', 'cancelled')),  -- Order fulfillment state
    total_amount DECIMAL(10, 2) NOT NULL
);

COMMENT ON TABLE orders IS 'Order transactions; one row per customer order. Time-series fact table.';
COMMENT ON COLUMN orders.id IS 'Unique order identifier.';
COMMENT ON COLUMN orders.customer_id IS 'Foreign key to customers.id; which customer placed this order.';
COMMENT ON COLUMN orders.created_at IS 'System timestamp when order record was created.';
COMMENT ON COLUMN orders.order_date IS 'Date when order was placed (for time-series queries, business date).';
COMMENT ON COLUMN orders.status IS 'Order fulfillment status: paid (fulfilled), refunded (money back), cancelled (not fulfilled).';
COMMENT ON COLUMN orders.total_amount IS 'Gross total amount (before discounts, in USD); equals SUM of order_items.unit_price * quantity.';

-- Order Items table: line items
CREATE TABLE order_items (
    id SERIAL PRIMARY KEY,
    order_id INT NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    product_id INT NOT NULL REFERENCES products(id) ON DELETE RESTRICT,
    quantity INT NOT NULL CHECK (quantity > 0),
    unit_price DECIMAL(10, 2) NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

COMMENT ON TABLE order_items IS 'Order line items; one row per product in an order (typically 3-5 items per order).';
COMMENT ON COLUMN order_items.id IS 'Unique line item identifier.';
COMMENT ON COLUMN order_items.order_id IS 'Foreign key to orders.id; which order this item belongs to.';
COMMENT ON COLUMN order_items.product_id IS 'Foreign key to products.id; which product was ordered.';
COMMENT ON COLUMN order_items.quantity IS 'Number of units ordered (>= 1).';
COMMENT ON COLUMN order_items.unit_price IS 'Price per unit at time of order (may differ from products.price due to discounts or bulk pricing).';
COMMENT ON COLUMN order_items.created_at IS 'System timestamp when item was added to order.';

-- Reviews table: customer product feedback
CREATE TABLE reviews (
    id SERIAL PRIMARY KEY,
    product_id INT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    customer_id INT NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    rating INT NOT NULL CHECK (rating BETWEEN 1 AND 5),
    comment TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

COMMENT ON TABLE reviews IS 'Customer product reviews; one row per review (one customer can review same product multiple times over time).';
COMMENT ON COLUMN reviews.id IS 'Unique review identifier.';
COMMENT ON COLUMN reviews.product_id IS 'Foreign key to products.id; which product is reviewed.';
COMMENT ON COLUMN reviews.customer_id IS 'Foreign key to customers.id; which customer wrote the review.';
COMMENT ON COLUMN reviews.rating IS 'Star rating: 1 (poor) to 5 (excellent).';
COMMENT ON COLUMN reviews.comment IS 'Optional text feedback.';
COMMENT ON COLUMN reviews.created_at IS 'System timestamp when review was created.';

-- Indexes for query performance and foreign key joins
CREATE INDEX idx_orders_customer_id ON orders(customer_id);
CREATE INDEX idx_orders_order_date ON orders(order_date);
CREATE INDEX idx_order_items_order_id ON order_items(order_id);
CREATE INDEX idx_order_items_product_id ON order_items(product_id);
CREATE INDEX idx_reviews_product_id ON reviews(product_id);
CREATE INDEX idx_reviews_customer_id ON reviews(customer_id);

-- Create read-only role and grant permissions
CREATE ROLE querypilot_ro NOLOGIN;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO querypilot_ro;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO querypilot_ro;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON ALL TABLES IN SCHEMA public FROM querypilot_ro;
```

### Foreign Keys and Indexes

- **Foreign Keys:**
  - orders.customer_id → customers.id (ON DELETE RESTRICT)
  - order_items.order_id → orders.id (ON DELETE CASCADE)
  - order_items.product_id → products.id (ON DELETE RESTRICT)
  - reviews.product_id → products.id (ON DELETE CASCADE)
  - reviews.customer_id → customers.id (ON DELETE CASCADE)

- **Indexes:**
  - idx_orders_customer_id (for joins: orders → customers)
  - idx_orders_order_date (for time-series filtering: WHERE order_date BETWEEN ...)
  - idx_order_items_order_id (for joins: order_items → orders)
  - idx_order_items_product_id (for joins: order_items → products)
  - idx_reviews_product_id (for joins: reviews → products)
  - idx_reviews_customer_id (for joins: reviews → customers)

### Example Queries Showing Join Patterns

**Simple aggregation (single table):**
```sql
SELECT COUNT(*) FROM customers;
SELECT SUM(total_amount) FROM orders WHERE status = 'paid';
SELECT AVG(rating) FROM reviews;
```

**Dual-table joins:**
```sql
SELECT c.name, COUNT(o.id) as order_count
FROM customers c
LEFT JOIN orders o ON c.id = o.customer_id
GROUP BY c.id, c.name
ORDER BY order_count DESC;
```

**Multi-table joins:**
```sql
SELECT p.name, SUM(oi.quantity) as total_sold, AVG(r.rating) as avg_rating
FROM products p
LEFT JOIN order_items oi ON p.id = oi.product_id
LEFT JOIN orders o ON oi.order_id = o.id AND o.status = 'paid'
LEFT JOIN reviews r ON p.id = r.product_id
GROUP BY p.id, p.name
ORDER BY total_sold DESC;
```

**Time-series (order_date filtering):**
```sql
SELECT 
    EXTRACT(YEAR FROM o.order_date) as year,
    EXTRACT(MONTH FROM o.order_date) as month,
    SUM(o.total_amount) as revenue
FROM orders o
WHERE o.status = 'paid'
GROUP BY YEAR(o.order_date), MONTH(o.order_date)
ORDER BY year, month;
```

---

## 3. Synthetic Data Generation

### Algorithm: Deterministic Seeding with NumPy/Random

**File: `seed/generator.py`**

```python
import random
from datetime import datetime, timedelta
import psycopg
from typing import Generator

class DataGenerator:
    """
    Deterministic synthetic data generator for e-commerce schema.
    Uses fixed random seed (default: 42) to ensure reproducibility.
    """
    
    def __init__(self, seed: int = 42, conn_str: str = None):
        self.seed = seed
        self.conn_str = conn_str
        random.seed(seed)
        
    def generate_customers(self, count: int = 500) -> Generator[dict, None, None]:
        """Generate synthetic customer records."""
        # Names, emails, states are pre-seeded and deterministic
        for i in range(count):
            yield {
                'name': self._synthetic_name(i),
                'email': f"{self._synthetic_name(i).replace(' ', '.')}.{random.randint(1000, 9999)}@example.com",
                'state': random.choice(['CA', 'NY', 'TX', 'FL', 'PA', 'IL', 'OH', 'GA', 'NC', 'MI']),
                'created_at': self._random_datetime_in_2024()
            }
    
    def generate_products(self, count: int = 50) -> Generator[dict, None, None]:
        """Generate synthetic product records."""
        categories = ['Electronics', 'Apparel', 'Home', 'Books', 'Sports']
        for i in range(count):
            yield {
                'name': f"Product {i+1}",
                'category': random.choice(categories),
                'price': round(random.uniform(10, 500), 2),
                'stock_quantity': random.randint(0, 1000),
                'created_at': self._random_datetime_in_2024()
            }
    
    def generate_orders(self, count: int = 5000, num_customers: int = 500) -> Generator[dict, None, None]:
        """
        Generate synthetic order records with Pareto distribution.
        ~60% in 2024, ~40% in 2025 to show growth.
        """
        for i in range(count):
            # Pareto: some customers have many orders, most have few
            customer_id = max(1, int(random.paretovariate(1)) % num_customers + 1)
            
            # Date distribution: 60% 2024, 40% 2025
            if random.random() < 0.6:
                order_date = self._random_date_in_2024()
            else:
                order_date = self._random_date_in_2025()
            
            status = random.choices(
                ['paid', 'refunded', 'cancelled'],
                weights=[0.85, 0.10, 0.05]
            )[0]
            
            yield {
                'customer_id': customer_id,
                'order_date': order_date,
                'status': status,
                'total_amount': round(random.uniform(20, 2000), 2)
            }
    
    def generate_order_items(self, orders: list, num_products: int = 50) -> Generator[dict, None, None]:
        """Generate 3-5 line items per order."""
        for order in orders:
            num_items = random.randint(3, 5)
            for _ in range(num_items):
                yield {
                    'order_id': order['id'],
                    'product_id': random.randint(1, num_products),
                    'quantity': random.randint(1, 10),
                    'unit_price': round(random.uniform(10, 300), 2)
                }
    
    def generate_reviews(self, count: int = 1250, num_customers: int = 500, num_products: int = 50) -> Generator[dict, None, None]:
        """Generate review records."""
        for i in range(count):
            yield {
                'product_id': random.randint(1, num_products),
                'customer_id': random.randint(1, num_customers),
                'rating': random.randint(1, 5),
                'comment': self._random_comment() if random.random() > 0.5 else None
            }
    
    def populate_database(self):
        """Execute generation and insert into database."""
        with psycopg.connect(self.conn_str) as conn:
            with conn.cursor() as cur:
                # Insert customers
                customers = list(self.generate_customers(500))
                for c in customers:
                    cur.execute(
                        "INSERT INTO customers (name, email, state, region, created_at) VALUES (%s, %s, %s, %s, %s)",
                        (c['name'], c['email'], c['state'], self._state_to_region(c['state']), c['created_at'])
                    )
                conn.commit()
                
                # Insert products
                products = list(self.generate_products(50))
                for p in products:
                    cur.execute(
                        "INSERT INTO products (name, category, price, stock_quantity, created_at) VALUES (%s, %s, %s, %s, %s)",
                        (p['name'], p['category'], p['price'], p['stock_quantity'], p['created_at'])
                    )
                conn.commit()
                
                # Insert orders
                orders = list(self.generate_orders(5000, 500))
                for o in orders:
                    cur.execute(
                        "INSERT INTO orders (customer_id, order_date, status, total_amount) VALUES (%s, %s, %s, %s)",
                        (o['customer_id'], o['order_date'], o['status'], o['total_amount'])
                    )
                conn.commit()
                
                # Fetch inserted order IDs for order_items
                cur.execute("SELECT id FROM orders ORDER BY id")
                order_ids = [row[0] for row in cur.fetchall()]
                
                # Insert order items
                order_items = list(self.generate_order_items([{'id': oid} for oid in order_ids], 50))
                for oi in order_items:
                    cur.execute(
                        "INSERT INTO order_items (order_id, product_id, quantity, unit_price) VALUES (%s, %s, %s, %s)",
                        (oi['order_id'], oi['product_id'], oi['quantity'], oi['unit_price'])
                    )
                conn.commit()
                
                # Insert reviews
                for r in self.generate_reviews(1250, 500, 50):
                    cur.execute(
                        "INSERT INTO reviews (product_id, customer_id, rating, comment) VALUES (%s, %s, %s, %s)",
                        (r['product_id'], r['customer_id'], r['rating'], r['comment'])
                    )
                conn.commit()
    
    # Helper methods
    def _synthetic_name(self, index: int) -> str:
        """Generate deterministic synthetic name."""
        first_names = ['John', 'Jane', 'Bob', 'Alice', 'Charlie', 'Diana', 'Eve', 'Frank']
        last_names = ['Smith', 'Johnson', 'Williams', 'Brown', 'Jones', 'Garcia', 'Miller', 'Davis']
        return f"{first_names[index % len(first_names)]} {last_names[(index // len(first_names)) % len(last_names)]}"
    
    def _state_to_region(self, state: str) -> str:
        """Map state to region."""
        regions = {
            'CA': 'West', 'WA': 'West', 'OR': 'West',
            'NY': 'Northeast', 'PA': 'Northeast', 'NJ': 'Northeast',
            'TX': 'South', 'FL': 'South', 'GA': 'South', 'NC': 'South',
            'IL': 'Midwest', 'OH': 'Midwest', 'MI': 'Midwest'
        }
        return regions.get(state, 'Other')
    
    def _random_datetime_in_2024(self) -> datetime:
        """Random datetime in 2024."""
        start = datetime(2024, 1, 1)
        end = datetime(2024, 12, 31, 23, 59, 59)
        return start + timedelta(seconds=random.randint(0, int((end - start).total_seconds())))
    
    def _random_date_in_2024(self) -> str:
        """Random date in 2024."""
        dt = self._random_datetime_in_2024()
        return dt.date().isoformat()
    
    def _random_date_in_2025(self) -> str:
        """Random date in 2025."""
        start = datetime(2025, 1, 1)
        end = datetime(2025, 12, 31, 23, 59, 59)
        dt = start + timedelta(seconds=random.randint(0, int((end - start).total_seconds())))
        return dt.date().isoformat()
    
    def _random_comment(self) -> str:
        """Random review comment."""
        comments = [
            "Great product!", "Excellent quality.", "Highly recommend.",
            "Good value for money.", "Very satisfied.", "As described.",
            "Not bad.", "Could be better.", "Disappointed."
        ]
        return random.choice(comments)
```

### Distribution Strategy

- **Customers:** 500 customers, uniformly seeded with deterministic names and emails
- **Products:** ~50 products across 5 categories (Electronics, Apparel, Home, Books, Sports)
- **Orders:** ~5,000 orders distributed:
  - **Pareto distribution** for customer orders: some customers have many (0–50), most have few (0–5)
  - **Temporal:** ~60% in 2024 (Jan–Dec), ~40% in 2025 (Jan–Dec) to show YoY comparison
  - **Status ratios:** 85% paid, 10% refunded, 5% cancelled (realistic fulfillment distribution)
- **Order Items:** 3–5 items per order (average 4), randomly selected from product catalog
- **Reviews:** 1,000–1,500 reviews, randomly distributed across products and customers, ratings 1–5 stars

### Data Flow: Generator Workflow

1. **Instantiate generator:** `gen = DataGenerator(seed=42, conn_str=TARGET_DB_URL)`
2. **Generate customers:** `gen.generate_customers(500)` → 500 records, deterministic
3. **Generate products:** `gen.generate_products(50)` → 50 records
4. **Generate orders:** `gen.generate_orders(5000, 500)` → 5000 records with Pareto + temporal distribution
5. **Generate order_items:** `gen.generate_order_items(orders, 50)` → ~20,000 line items
6. **Generate reviews:** `gen.generate_reviews(1250, 500, 50)` → ~1,250 reviews
7. **Populate database:** `gen.populate_database()` → INSERT all data in batches

### Verification: Row Count and FK Integrity Checks

**In `seed/verify.py`:**

```python
def verify_data():
    """Verify seeded data meets expectations."""
    with psycopg.connect(TARGET_DB_URL) as conn:
        with conn.cursor() as cur:
            # Row counts
            cur.execute("SELECT COUNT(*) FROM customers")
            assert cur.fetchone()[0] == 500, "Expected 500 customers"
            
            cur.execute("SELECT COUNT(*) FROM products")
            assert cur.fetchone()[0] == 50, "Expected 50 products"
            
            cur.execute("SELECT COUNT(*) FROM orders")
            order_count = cur.fetchone()[0]
            assert 4900 <= order_count <= 5100, f"Expected ~5000 orders, got {order_count}"
            
            # Foreign key integrity (no orphaned rows)
            cur.execute("""
                SELECT COUNT(*) FROM orders o
                WHERE NOT EXISTS (SELECT 1 FROM customers c WHERE c.id = o.customer_id)
            """)
            assert cur.fetchone()[0] == 0, "Orphaned orders (customer_id not found)"
            
            cur.execute("""
                SELECT COUNT(*) FROM order_items oi
                WHERE NOT EXISTS (SELECT 1 FROM orders o WHERE o.id = oi.order_id)
            """)
            assert cur.fetchone()[0] == 0, "Orphaned order_items (order_id not found)"
            
            # Status distribution
            cur.execute("""
                SELECT status, COUNT(*) FROM orders GROUP BY status
            """)
            status_dist = dict(cur.fetchall())
            total = sum(status_dist.values())
            paid_pct = status_dist['paid'] / total
            assert 0.80 <= paid_pct <= 0.90, f"Expected ~85% paid, got {paid_pct*100:.1f}%"
```

---

## 4. Docker Compose Architecture

### Two PostgreSQL Services: target_db and app_db

**File: `docker-compose.yml`**

```yaml
version: "3.9"

services:
  target_db:
    image: postgres:16-alpine
    container_name: querypilot_target_db
    environment:
      POSTGRES_DB: querypilot_target
      POSTGRES_USER: analytics_user
      POSTGRES_PASSWORD: ${TARGET_DB_PASSWORD:-targetdb_password}
      POSTGRES_INITDB_ARGS: "--encoding=UTF8"
    ports:
      - "${TARGET_DB_PORT:-5433}:5432"
    volumes:
      - ./seed/schema.sql:/docker-entrypoint-initdb.d/01-schema.sql
      - ./seed/generator.py:/docker-entrypoint-initdb.d/02-generator.py
      - target_db_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U analytics_user -d querypilot_target"]
      interval: 5s
      timeout: 10s
      retries: 5
      start_period: 10s
    networks:
      - querypilot_net

  app_db:
    image: postgres:16-alpine
    container_name: querypilot_app_db
    environment:
      POSTGRES_DB: querypilot_app
      POSTGRES_USER: app_user
      POSTGRES_PASSWORD: ${APP_DB_PASSWORD:-appdb_password}
      POSTGRES_INITDB_ARGS: "--encoding=UTF8"
    ports:
      - "${APP_DB_PORT:-5432}:5432"
    volumes:
      - ./seed/app_schema.sql:/docker-entrypoint-initdb.d/01-app-schema.sql
      - app_db_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U app_user -d querypilot_app"]
      interval: 5s
      timeout: 10s
      retries: 5
      start_period: 10s
    networks:
      - querypilot_net

volumes:
  target_db_data:
    driver: local
  app_db_data:
    driver: local

networks:
  querypilot_net:
    driver: bridge
```

### Initialization: Schema + Data

**target_db initialization (docker-entrypoint-initdb.d):**
1. `01-schema.sql`: Load DDL, create 5 tables, create querypilot_ro role, grant permissions
2. `02-generator.py`: Python script that connects to database, runs `DataGenerator().populate_database()` to insert synthetic data

**app_db initialization:**
1. `01-app-schema.sql`: Create conversations, query_log, eval_runs tables

### Health Checks

- **target_db:** `pg_isready -U analytics_user -d querypilot_target` every 5s, timeout 10s, retries 5
- **app_db:** `pg_isready -U app_user -d querypilot_app` every 5s, timeout 10s, retries 5
- **Startup delay:** 10s before first health check (allow DB startup)

### Environment Configuration

- `TARGET_DB_PASSWORD`: Read from env var or default to "targetdb_password" (for dev only)
- `APP_DB_PASSWORD`: Read from env var or default to "appdb_password" (for dev only)
- `TARGET_DB_PORT`: Port mapping for target_db (default: 5433)
- `APP_DB_PORT`: Port mapping for app_db (default: 5432)

These env vars are typically set in `.env` file or via `docker-compose.override.yml` for local dev.

### Container Lifecycle Commands

```bash
# Start services
docker-compose up -d

# Wait for health checks to pass
docker-compose ps  # Check STATUS column

# Run commands inside container
docker-compose exec target_db psql -U analytics_user -d querypilot_target -c "SELECT COUNT(*) FROM customers"

# Stop services (keep data)
docker-compose stop

# Remove containers (data persists in volumes)
docker-compose down

# Remove containers and volumes (full reset)
docker-compose down -v

# View logs
docker-compose logs -f target_db
```

---

## 5. Baseline LLM Client Design

### Abstract Interface

**File: `eval/baseline.py` (partial)**

```python
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any

class LLMClient(ABC):
    """Abstract interface for LLM providers."""
    
    @abstractmethod
    def call(self, prompt: str) -> str:
        """
        Send a prompt to the LLM and return the response.
        
        Args:
            prompt: The prompt to send (includes schema, context, question)
            
        Returns:
            str: The LLM's response (expected to contain SQL)
            
        Raises:
            LLMError: On API error, auth error, timeout, or rate limit
        """
        pass
    
    def __repr__(self) -> str:
        raise NotImplementedError

class LLMError(Exception):
    """Base error for LLM client issues."""
    def __init__(self, provider: str, error_category: str, message: str):
        self.provider = provider
        self.error_category = error_category
        self.message = message
        super().__init__(f"{provider} ({error_category}): {message}")
```

### Concrete Implementations

**OpenAI Client:**

```python
import openai

class OpenAIClient(LLMClient):
    """OpenAI API client."""
    
    def __init__(self, api_key: str, model: str = "gpt-4-turbo", **kwargs):
        self.api_key = api_key
        self.model = model
        self.temperature = kwargs.get('temperature', 0.0)
        self.max_tokens = kwargs.get('max_tokens', 2048)
        openai.api_key = api_key
    
    def call(self, prompt: str) -> str:
        try:
            response = openai.ChatCompletion.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are a PostgreSQL SQL expert."},
                    {"role": "user", "content": prompt}
                ],
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                timeout=30
            )
            return response['choices'][0]['message']['content']
        except openai.error.AuthenticationError as e:
            raise LLMError("openai", "auth_error", str(e))
        except openai.error.RateLimitError as e:
            raise LLMError("openai", "rate_limit", str(e))
        except openai.error.Timeout as e:
            raise LLMError("openai", "timeout", str(e))
        except Exception as e:
            raise LLMError("openai", "api_error", str(e))
    
    def __repr__(self) -> str:
        return f"OpenAIClient(model={self.model})"
```

**Anthropic Client:**

```python
import anthropic

class AnthropicClient(LLMClient):
    """Anthropic API client."""
    
    def __init__(self, api_key: str, model: str = "claude-3-opus-20240229", **kwargs):
        self.api_key = api_key
        self.model = model
        self.temperature = kwargs.get('temperature', 0.0)
        self.max_tokens = kwargs.get('max_tokens', 2048)
        self.client = anthropic.Anthropic(api_key=api_key)
    
    def call(self, prompt: str) -> str:
        try:
            message = self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                messages=[
                    {"role": "user", "content": prompt}
                ],
                temperature=self.temperature
            )
            return message.content[0].text
        except anthropic.AuthenticationError as e:
            raise LLMError("anthropic", "auth_error", str(e))
        except anthropic.RateLimitError as e:
            raise LLMError("anthropic", "rate_limit", str(e))
        except anthropic.APITimeout as e:
            raise LLMError("anthropic", "timeout", str(e))
        except Exception as e:
            raise LLMError("anthropic", "api_error", str(e))
    
    def __repr__(self) -> str:
        return f"AnthropicClient(model={self.model})"
```

**Bedrock Client:**

```python
import boto3

class BedrockClient(LLMClient):
    """AWS Bedrock client for Anthropic Claude models."""
    
    def __init__(self, model: str = "anthropic.claude-3-sonnet-20240229-v1:0", region: str = "us-east-1", **kwargs):
        self.model = model
        self.region = region
        self.temperature = kwargs.get('temperature', 0.0)
        self.max_tokens = kwargs.get('max_tokens', 2048)
        self.client = boto3.client('bedrock-runtime', region_name=region)
    
    def call(self, prompt: str) -> str:
        try:
            response = self.client.invoke_model(
                modelId=self.model,
                body=json.dumps({
                    "anthropic_version": "bedrock-2023-06-01",
                    "max_tokens": self.max_tokens,
                    "temperature": self.temperature,
                    "messages": [
                        {"role": "user", "content": prompt}
                    ]
                })
            )
            response_body = json.loads(response['body'].read())
            return response_body['content'][0]['text']
        except Exception as e:
            # Bedrock errors mapped to generic LLMError
            raise LLMError("bedrock", "api_error", str(e))
    
    def __repr__(self) -> str:
        return f"BedrockClient(model={self.model}, region={self.region})"
```

### Factory Pattern: Instantiate Based on Environment

```python
def get_llm_client(config: Config) -> LLMClient:
    """
    Factory function to instantiate correct LLMClient based on config.
    
    Args:
        config: Pydantic Settings object with LLM_PROVIDER, LLM_MODEL, etc.
        
    Returns:
        LLMClient: Concrete instance (OpenAI, Anthropic, or Bedrock)
        
    Raises:
        ConfigError: If provider not recognized or credentials missing
    """
    provider = config.llm_provider.lower()
    model = config.llm_model
    
    if provider == "openai":
        api_key = config.openai_api_key
        if not api_key:
            raise ConfigError("Missing required env var: OPENAI_API_KEY")
        return OpenAIClient(api_key, model, temperature=config.llm_temperature, max_tokens=config.llm_max_tokens)
    
    elif provider == "anthropic":
        api_key = config.anthropic_api_key
        if not api_key:
            raise ConfigError("Missing required env var: ANTHROPIC_API_KEY")
        return AnthropicClient(api_key, model, temperature=config.llm_temperature, max_tokens=config.llm_max_tokens)
    
    elif provider == "bedrock":
        # AWS credentials read from environment or config
        return BedrockClient(model, region=config.aws_region, temperature=config.llm_temperature, max_tokens=config.llm_max_tokens)
    
    else:
        raise ConfigError(f"Unknown LLM provider: {provider}. Choose from: openai, anthropic, bedrock")
```

### Error Handling

- **LLMError:** Base exception for all LLM client failures
- **Auth errors:** Raised on invalid credentials (OPENAI_API_KEY missing, invalid Bedrock IAM role, etc.)
- **Timeouts:** Raised if LLM API takes >30s to respond
- **Rate limits:** Raised if API returns 429 (retry later logic deferred to caller)
- **API errors:** Catch-all for other errors (sanitized before logging)

### Security: Never Log Credentials

```python
# ✓ Good: log provider and model, not credentials
logger.info(f"LLM call: provider={client}, model={config.llm_model}")

# ✗ Bad: never do this
logger.info(f"Using API key: {config.openai_api_key}")  # LEAK!
```

---

## 6. Baseline Text-to-SQL Function Design

### Input and Function Signature

```python
def baseline_text_to_sql(
    question: str,
    schema_context: str,
    config: Config,
    llm_client: LLMClient
) -> str:
    """
    Single-call baseline: send schema + question to LLM, extract SQL.
    
    Args:
        question: Natural-language question from user
        schema_context: Full Target DB DDL + table descriptions
        config: Configuration (including query timeout, row limit, etc.)
        llm_client: LLMClient instance (OpenAI, Anthropic, or Bedrock)
    
    Returns:
        str: Extracted SQL from LLM response (no validation, as-is)
        
    Raises:
        LLMError: On LLM API failure
        InvalidResponseError: If LLM response contains no extractable SQL
    """
```

### Prompt Construction

```python
def construct_prompt(question: str, schema_context: str) -> str:
    """Construct prompt for LLM."""
    prompt = f"""
You are a PostgreSQL SQL expert. Given a database schema and a natural-language question, 
write a single SELECT statement to answer the question.

## Database Schema

{schema_context}

## Instructions
- Return ONLY valid PostgreSQL SQL.
- Do not include explanations, code blocks, or markdown.
- Do not use CREATE, INSERT, UPDATE, DELETE, or DROP statements.
- Use table aliases for clarity (e.g., `c` for customers, `o` for orders).
- Include a comment line before the SELECT if needed for clarity.
- For date comparisons, use DATE or TIMESTAMP types appropriately.

## Question

{question}

## SQL
"""
    return prompt
```

### LLM Call and Response Parsing

```python
def baseline_text_to_sql(question: str, schema_context: str, config: Config, llm_client: LLMClient) -> str:
    # Construct prompt
    prompt = construct_prompt(question, schema_context)
    
    # Call LLM
    try:
        response = llm_client.call(prompt)
    except LLMError as e:
        logger.error(f"LLM call failed: {e}")
        raise
    
    # Extract SQL from response (remove markdown code blocks if present)
    sql = extract_sql(response)
    
    if not sql:
        raise InvalidResponseError(f"No SQL found in response: {response[:100]}")
    
    return sql

def extract_sql(response: str) -> str:
    """Extract SQL from markdown-formatted response."""
    # Remove code block markers: ```sql ... ``` or ``` ... ```
    import re
    
    # Try to find SQL in markdown code blocks
    match = re.search(r'```(?:sql)?\s*(.*?)\s*```', response, re.DOTALL | re.IGNORECASE)
    if match:
        sql = match.group(1).strip()
    else:
        # Fallback: return entire response, stripped
        sql = response.strip()
    
    # Clean up: remove leading/trailing whitespace, semicolon
    sql = sql.strip().rstrip(';')
    
    return sql
```

### Output: Extracted SQL String (No Validation)

The baseline **does not validate** the extracted SQL. This is intentional—we want to measure the baseline performance without safety guardrails. Validation is added in later phases.

### Logging: Query Log Table in App DB

```python
def log_query(
    question: str,
    provider: str,
    model: str,
    extracted_sql: str,
    tokens_used: Optional[int] = None,
    config: Config = None
):
    """Log baseline query to App DB for durability and analysis."""
    import json
    from datetime import datetime
    
    with psycopg.connect(config.app_db_url) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO query_log 
                (timestamp, question, provider, model, generated_sql, tokens_used, metadata)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (
                datetime.utcnow(),
                question,
                provider,
                model,
                extracted_sql,
                tokens_used,
                json.dumps({"baseline": True, "phase": "seed_db_baseline"})
            ))
            conn.commit()
```

---

## 7. Evaluation Dataset Design

### Format and Schema

**File: `eval/dataset.jsonl`**

Each line is a JSON object:

```json
{
  "question": "How many customers are there?",
  "gold_sql": "SELECT COUNT(*) as customer_count FROM customers;",
  "expected_tables": ["customers"],
  "category": "simple_aggregation"
}
```

### 20 Starter Items: Balanced Categories

**Simple Aggregation (5 items):**

1. "How many customers are there?"
   - gold_sql: `SELECT COUNT(*) as customer_count FROM customers;`
   - expected_tables: ["customers"]

2. "What is the average order amount?"
   - gold_sql: `SELECT AVG(total_amount) as avg_order_amount FROM orders WHERE status = 'paid';`
   - expected_tables: ["orders"]

3. "What is the total revenue by product category?"
   - gold_sql: `SELECT p.category, SUM(oi.quantity * oi.unit_price) as revenue FROM products p LEFT JOIN order_items oi ON p.id = oi.product_id GROUP BY p.category ORDER BY revenue DESC;`
   - expected_tables: ["products", "order_items"]

4. "How many paid vs. refunded vs. cancelled orders are there?"
   - gold_sql: `SELECT status, COUNT(*) as order_count FROM orders GROUP BY status ORDER BY order_count DESC;`
   - expected_tables: ["orders"]

5. "What is the most popular product by units sold?"
   - gold_sql: `SELECT p.name, SUM(oi.quantity) as units_sold FROM products p LEFT JOIN order_items oi ON p.id = oi.product_id GROUP BY p.id, p.name ORDER BY units_sold DESC LIMIT 1;`
   - expected_tables: ["products", "order_items"]

**Joins (5 items):**

6. "Show me all orders with customer names."
   - gold_sql: `SELECT o.id, c.name, o.order_date, o.total_amount FROM orders o JOIN customers c ON o.customer_id = c.id;`
   - expected_tables: ["orders", "customers"]

7. "Top 5 customers by number of orders placed."
   - gold_sql: `SELECT c.id, c.name, COUNT(o.id) as order_count FROM customers c LEFT JOIN orders o ON c.id = o.customer_id GROUP BY c.id, c.name ORDER BY order_count DESC LIMIT 5;`
   - expected_tables: ["customers", "orders"]

8. "List all products that have been ordered, with customer names."
   - gold_sql: `SELECT DISTINCT p.id, p.name, c.name FROM products p JOIN order_items oi ON p.id = oi.product_id JOIN orders o ON oi.order_id = o.id JOIN customers c ON o.customer_id = c.id;`
   - expected_tables: ["products", "order_items", "orders", "customers"]

9. "Show orders with their review ratings."
   - gold_sql: `SELECT o.id, o.order_date, o.total_amount, AVG(r.rating) as avg_rating FROM orders o LEFT JOIN order_items oi ON o.id = oi.order_id LEFT JOIN reviews r ON oi.product_id = r.product_id GROUP BY o.id;`
   - expected_tables: ["orders", "order_items", "reviews"]

10. "Revenue by customer region."
    - gold_sql: `SELECT c.region, SUM(o.total_amount) as revenue FROM customers c LEFT JOIN orders o ON c.id = o.customer_id WHERE o.status = 'paid' GROUP BY c.region ORDER BY revenue DESC;`
    - expected_tables: ["customers", "orders"]

**Time Comparison (5 items):**

11. "Compare total orders in 2024 vs. 2025."
    - gold_sql: `SELECT EXTRACT(YEAR FROM order_date) as year, COUNT(*) as order_count FROM orders WHERE status = 'paid' GROUP BY EXTRACT(YEAR FROM order_date) ORDER BY year;`
    - expected_tables: ["orders"]

12. "Year-over-year revenue comparison (2024 vs. 2025)."
    - gold_sql: `SELECT EXTRACT(YEAR FROM order_date) as year, SUM(total_amount) as revenue FROM orders WHERE status = 'paid' GROUP BY EXTRACT(YEAR FROM order_date) ORDER BY year;`
    - expected_tables: ["orders"]

13. "Month-over-month order growth in 2025."
    - gold_sql: `SELECT EXTRACT(MONTH FROM order_date) as month, COUNT(*) as order_count FROM orders WHERE EXTRACT(YEAR FROM order_date) = 2025 GROUP BY EXTRACT(MONTH FROM order_date) ORDER BY month;`
    - expected_tables: ["orders"]

14. "Orders created in Q4 2024 (Oct-Dec 2024)."
    - gold_sql: `SELECT COUNT(*) as q4_2024_orders FROM orders WHERE order_date >= '2024-10-01' AND order_date < '2025-01-01' AND status = 'paid';`
    - expected_tables: ["orders"]

15. "Customer acquisition trend by month in 2024."
    - gold_sql: `SELECT EXTRACT(MONTH FROM created_at) as month, COUNT(*) as new_customers FROM customers WHERE EXTRACT(YEAR FROM created_at) = 2024 GROUP BY EXTRACT(MONTH FROM created_at) ORDER BY month;`
    - expected_tables: ["customers"]

**Ambiguous (5 items):**

16. "Revenue trend over time." (Interpret as: monthly revenue in 2024–2025)
    - gold_sql: `SELECT DATE_TRUNC('month', order_date) as month, SUM(total_amount) as revenue FROM orders WHERE status = 'paid' GROUP BY DATE_TRUNC('month', order_date) ORDER BY month;`
    - expected_tables: ["orders"]
    - Note: Ambiguous because "revenue trend" could mean daily, weekly, monthly, or by category. Gold interpretation: monthly by default.

17. "Top customers." (Interpret as: by total spend)
    - gold_sql: `SELECT c.id, c.name, SUM(o.total_amount) as total_spend FROM customers c LEFT JOIN orders o ON c.id = o.customer_id WHERE o.status = 'paid' GROUP BY c.id, c.name ORDER BY total_spend DESC LIMIT 10;`
    - expected_tables: ["customers", "orders"]

18. "Best sellers." (Interpret as: products by units sold)
    - gold_sql: `SELECT p.id, p.name, SUM(oi.quantity) as units_sold FROM products p LEFT JOIN order_items oi ON p.id = oi.product_id GROUP BY p.id, p.name ORDER BY units_sold DESC LIMIT 10;`
    - expected_tables: ["products", "order_items"]

19. "Customer engagement." (Interpret as: customers with recent orders)
    - gold_sql: `SELECT c.id, c.name, COUNT(o.id) as order_count, MAX(o.order_date) as last_order_date FROM customers c LEFT JOIN orders o ON c.id = o.customer_id GROUP BY c.id, c.name HAVING MAX(o.order_date) >= CURRENT_DATE - INTERVAL '90 days';`
    - expected_tables: ["customers", "orders"]

20. "Sales trends by category." (Interpret as: revenue by product category over time)
    - gold_sql: `SELECT DATE_TRUNC('quarter', o.order_date) as quarter, p.category, SUM(oi.quantity * oi.unit_price) as revenue FROM products p LEFT JOIN order_items oi ON p.id = oi.product_id LEFT JOIN orders o ON oi.order_id = o.id WHERE o.status = 'paid' GROUP BY DATE_TRUNC('quarter', o.order_date), p.category ORDER BY quarter, revenue DESC;`
    - expected_tables: ["products", "order_items", "orders"]

### Validation of Gold SQL

All gold_sql queries must be:
- **Syntactically valid PostgreSQL**
- **Executable against Target DB with seed data** (no runtime errors)
- **Return non-empty results** (or explicitly noted as edge case if 0 results expected)

---

## 8. Baseline Evaluation Execution Design

### Process Per Item

**File: `eval/run_eval.py`**

```python
def run_baseline_evaluation(
    config: Config,
    dataset_path: str = "eval/dataset.jsonl",
    output_json: str = "eval/baseline_results.json"
):
    """Run baseline evaluation against 20-item dataset."""
    
    # Load dataset
    items = load_jsonl(dataset_path)
    
    # Initialize LLM client
    llm_client = get_llm_client(config)
    
    # Fetch schema once (for all questions)
    schema_context = fetch_schema_from_target_db(config)
    
    # Results
    results = []
    
    for i, item in enumerate(items, 1):
        question = item['question']
        gold_sql = item['gold_sql']
        expected_tables = item['expected_tables']
        category = item['category']
        
        logger.info(f"Item {i}/{len(items)}: {category} - {question[:50]}...")
        
        result = {
            'item_index': i,
            'question': question,
            'category': category,
            'expected_tables': expected_tables,
            'gold_sql': gold_sql,
            'generated_sql': None,
            'result_match': False,
            'error': None,
            'error_type': None
        }
        
        # 1. Call baseline LLM
        try:
            generated_sql = baseline_text_to_sql(question, schema_context, config, llm_client)
            result['generated_sql'] = generated_sql
        except LLMError as e:
            result['error'] = str(e)
            result['error_type'] = 'llm_error'
            logger.error(f"LLM error: {e}")
            results.append(result)
            continue
        except InvalidResponseError as e:
            result['error'] = str(e)
            result['error_type'] = 'response_parsing_error'
            logger.error(f"Response parsing error: {e}")
            results.append(result)
            continue
        
        # 2. Execute generated SQL
        generated_result = None
        try:
            generated_result = execute_sql(generated_sql, config, timeout=config.query_timeout_seconds)
        except Exception as e:
            result['error'] = sanitize_error(str(e))
            result['error_type'] = 'execution_error'
            logger.error(f"Execution error (generated): {e}")
            results.append(result)
            continue
        
        # 3. Execute gold SQL
        gold_result = None
        try:
            gold_result = execute_sql(gold_sql, config, timeout=config.query_timeout_seconds)
        except Exception as e:
            result['error'] = sanitize_error(str(e))
            result['error_type'] = 'gold_execution_error'
            logger.error(f"Execution error (gold): {e}")
            results.append(result)
            continue
        
        # 4. Compare result sets
        try:
            match = compare_result_sets(generated_result, gold_result, order_sensitive=False)
            result['result_match'] = match
            if not match:
                result['error'] = "Result set mismatch (row count or values differ)"
        except Exception as e:
            result['error'] = sanitize_error(str(e))
            result['error_type'] = 'comparison_error'
            logger.error(f"Comparison error: {e}")
        
        # 5. Log to App DB
        log_query(
            question=question,
            provider=llm_client.__class__.__name__,
            model=config.llm_model,
            extracted_sql=generated_sql,
            config=config
        )
        
        results.append(result)
    
    # Compute metrics
    metrics = compute_metrics(results)
    
    # Log full run to App DB
    log_eval_run(config, llm_client.__class__.__name__, config.llm_model, results, metrics)
    
    # Print summary
    print_summary(metrics, results)
    
    # Save detailed report
    save_json_report(results, metrics, output_json)
```

### SQL Execution with Timeout and Row Limit

```python
def execute_sql(
    sql: str,
    config: Config,
    timeout: int = 5
) -> list[dict]:
    """
    Execute SQL against Target DB (using querypilot_ro role).
    
    Args:
        sql: SQL query string
        config: Configuration (database URL, timeout, row limit)
        timeout: Query timeout in seconds (default: 5)
    
    Returns:
        list[dict]: Result rows (columns as keys)
        
    Raises:
        ExecutionError: On syntax error, runtime error, timeout
    """
    try:
        with psycopg.connect(config.target_db_url, connect_timeout=10) as conn:
            # Set connection parameters
            with conn.cursor() as cur:
                # Read-only transaction
                cur.execute("SET TRANSACTION READ ONLY;")
                
                # Query timeout
                cur.execute(f"SET statement_timeout = {timeout * 1000};")  # milliseconds
                
                # Execute query
                cur.execute(sql)
                
                # Fetch up to row limit
                rows = cur.fetchall()
                if len(rows) > config.result_row_limit:
                    logger.warning(f"Query returned {len(rows)} rows, truncating to {config.result_row_limit}")
                    rows = rows[:config.result_row_limit]
                
                # Convert to list of dicts (columns as keys)
                columns = [desc[0] for desc in cur.description]
                return [dict(zip(columns, row)) for row in rows]
    
    except psycopg.errors.SyntaxError as e:
        raise ExecutionError(error_type='syntax_error', message=sanitize_error(str(e)))
    except psycopg.errors.OperationalError as e:
        if 'timeout' in str(e).lower():
            raise ExecutionError(error_type='timeout', message=f"Query exceeded {timeout}s timeout")
        raise ExecutionError(error_type='operational_error', message=sanitize_error(str(e)))
    except Exception as e:
        raise ExecutionError(error_type='execution_error', message=sanitize_error(str(e)))
```

### Result Set Comparison (Order-Insensitive)

```python
def compare_result_sets(generated: list[dict], gold: list[dict], order_sensitive: bool = False) -> bool:
    """
    Compare two result sets (row and column order independent by default).
    
    Args:
        generated: Result from generated SQL
        gold: Result from gold SQL
        order_sensitive: If True, row order must match (default: False)
    
    Returns:
        bool: True if result sets are equivalent, False otherwise
    """
    if len(generated) != len(gold):
        return False
    
    if not generated and not gold:
        return True  # Both empty
    
    if generated[0].keys() != gold[0].keys():
        return False  # Column names differ
    
    if order_sensitive:
        return generated == gold
    else:
        # Order-insensitive: convert to sets (rows must be hashable)
        try:
            gen_set = set(tuple(sorted(row.items())) for row in generated)
            gold_set = set(tuple(sorted(row.items())) for row in gold)
            return gen_set == gold_set
        except TypeError:
            # Unhashable values (lists, dicts); fall back to element-wise comparison
            return sorted(generated, key=str) == sorted(gold, key=str)
```

### Output Metrics

**Metrics computation:**

```python
def compute_metrics(results: list[dict]) -> dict:
    """Compute evaluation metrics from results."""
    total = len(results)
    matches = sum(1 for r in results if r.get('result_match'))
    errors = sum(1 for r in results if r.get('error'))
    successes = total - errors
    
    # By category
    by_category = {}
    for category in ['simple_aggregation', 'joins', 'time_comparison', 'ambiguous']:
        cat_results = [r for r in results if r['category'] == category]
        cat_matches = sum(1 for r in cat_results if r.get('result_match'))
        by_category[category] = {
            'total': len(cat_results),
            'matches': cat_matches,
            'accuracy': cat_matches / len(cat_results) if cat_results else 0
        }
    
    # Error breakdown
    error_types = {}
    for r in results:
        if r.get('error_type'):
            error_types[r['error_type']] = error_types.get(r['error_type'], 0) + 1
    
    return {
        'overall_accuracy': matches / total,
        'coverage': successes / total,
        'error_rate': errors / total,
        'by_category': by_category,
        'error_breakdown': error_types,
        'total_items': total,
        'matches': matches,
        'errors': errors
    }
```

### Logging Evaluation Run

```python
def log_eval_run(
    config: Config,
    provider: str,
    model: str,
    results: list[dict],
    metrics: dict
):
    """Log full evaluation run to App DB."""
    import json
    from datetime import datetime
    
    with psycopg.connect(config.app_db_url) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO eval_runs 
                (run_timestamp, baseline_provider, baseline_model, overall_accuracy, category_breakdown, full_results)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (
                datetime.utcnow(),
                provider,
                model,
                metrics['overall_accuracy'],
                json.dumps(metrics['by_category']),
                json.dumps(results)
            ))
            conn.commit()
```

### Summary Output and JSON Report

**Print to stdout:**

```
================================================================================
Baseline Text-to-SQL Evaluation Results
================================================================================
Overall Accuracy: 75% (15/20 items)
Coverage: 95% (19/20 items, 1 error)
Error Rate: 5% (1/20 items)

By Category:
  simple_aggregation: 80% (4/5)
  joins:              60% (3/5)
  time_comparison:    100% (5/5)
  ambiguous:          65% (3/5)

Error Breakdown:
  execution_error:    1

Detailed Results: eval/baseline_results.json
Full Run Logged to App DB (eval_runs table)
================================================================================
```

**Save to `eval/baseline_results.json`:**

```json
{
  "run_id": "2024-01-15T10:30:45Z",
  "metadata": {
    "provider": "OpenAIClient",
    "model": "gpt-4-turbo",
    "seed_db_baseline_phase": true
  },
  "metrics": {
    "overall_accuracy": 0.75,
    "coverage": 0.95,
    "error_rate": 0.05,
    "by_category": {
      "simple_aggregation": {"total": 5, "matches": 4, "accuracy": 0.8},
      "joins": {"total": 5, "matches": 3, "accuracy": 0.6},
      "time_comparison": {"total": 5, "matches": 5, "accuracy": 1.0},
      "ambiguous": {"total": 5, "matches": 3, "accuracy": 0.6}
    },
    "error_breakdown": {
      "execution_error": 1
    }
  },
  "results": [
    {
      "item_index": 1,
      "question": "How many customers are there?",
      "category": "simple_aggregation",
      "gold_sql": "SELECT COUNT(*) as customer_count FROM customers;",
      "generated_sql": "SELECT COUNT(*) FROM customers;",
      "result_match": true,
      "error": null
    },
    ...
  ]
}
```

---

## 9. Configuration & Secrets Management

### Pydantic BaseSettings

**File: `app/config.py`**

```python
from pydantic_settings import BaseSettings
from typing import Optional

class Config(BaseSettings):
    # Database
    target_db_url: str  # No default; required
    app_db_url: str  # No default; required
    target_db_readonly_role: str = "querypilot_ro"
    query_timeout_seconds: int = 5
    result_row_limit: int = 1000
    
    # LLM
    llm_provider: str  # "openai", "anthropic", "bedrock"; required
    llm_model: str  # required; e.g., "gpt-4-turbo"
    llm_temperature: float = 0.0
    llm_max_tokens: int = 2048
    
    # Provider-specific keys (optional; depends on provider)
    openai_api_key: Optional[str] = None
    anthropic_api_key: Optional[str] = None
    aws_access_key_id: Optional[str] = None
    aws_secret_access_key: Optional[str] = None
    aws_region: str = "us-east-1"
    
    # Debug
    debug: bool = False
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False
    
    def validate_required_vars(self):
        """Validate that all required variables are set."""
        errors = []
        
        if not self.target_db_url:
            errors.append("Missing required env var: TARGET_DB_URL")
        if not self.app_db_url:
            errors.append("Missing required env var: APP_DB_URL")
        if not self.llm_provider:
            errors.append("Missing required env var: LLM_PROVIDER")
        if not self.llm_model:
            errors.append("Missing required env var: LLM_MODEL")
        
        # Provider-specific validation
        provider = self.llm_provider.lower() if self.llm_provider else None
        if provider == "openai" and not self.openai_api_key:
            errors.append("Missing required env var: OPENAI_API_KEY (for provider=openai)")
        if provider == "anthropic" and not self.anthropic_api_key:
            errors.append("Missing required env var: ANTHROPIC_API_KEY (for provider=anthropic)")
        if provider == "bedrock" and not (self.aws_access_key_id and self.aws_secret_access_key):
            errors.append("Missing required env vars: AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY (for provider=bedrock)")
        
        if errors:
            raise ValueError("\n".join(errors))
    
    def __init__(self, **data):
        super().__init__(**data)
        self.validate_required_vars()
```

### `.env.example`

```bash
# Database Configuration
# Target DB: analytics data, read-only role for queries
TARGET_DB_URL=postgresql://analytics_user:targetdb_password@localhost:5433/querypilot_target
TARGET_DB_READONLY_ROLE=querypilot_ro

# App DB: QueryPilot's metadata (conversations, query_log, eval_runs)
APP_DB_URL=postgresql://app_user:appdb_password@localhost:5432/querypilot_app

# Query Execution
QUERY_TIMEOUT_SECONDS=5
RESULT_ROW_LIMIT=1000

# LLM Provider Configuration
# Options: "openai", "anthropic", "bedrock"
LLM_PROVIDER=openai
LLM_MODEL=gpt-4-turbo

# LLM Parameters
LLM_TEMPERATURE=0.0
LLM_MAX_TOKENS=2048

# OpenAI (if LLM_PROVIDER=openai)
OPENAI_API_KEY=sk-...

# Anthropic (if LLM_PROVIDER=anthropic)
ANTHROPIC_API_KEY=sk-ant-...

# AWS Bedrock (if LLM_PROVIDER=bedrock)
AWS_ACCESS_KEY_ID=AKIA...
AWS_SECRET_ACCESS_KEY=...
AWS_REGION=us-east-1

# Debug
DEBUG=false
```

### Never Log Credentials

```python
# ✓ Good: Log non-sensitive config
logger.info(f"LLM: provider={config.llm_provider}, model={config.llm_model}")

# ✗ Bad: Never log these
logger.info(f"API Key: {config.openai_api_key}")  # LEAK!
logger.info(f"DB URL: {config.target_db_url}")    # Exposes password!

# ✓ Good: Mask or omit in logs
logger.info(f"DB: postgresql://...@localhost:5433/querypilot_target")
```

---

## 10. Verification & Health Checks

### `seed.verify`: Database Verification

**File: `seed/verify.py`**

```python
import sys
import psycopg
from app.config import Config

def verify_schema(config: Config) -> list[str]:
    """Verify Target DB schema is correct."""
    errors = []
    
    with psycopg.connect(config.target_db_url) as conn:
        with conn.cursor() as cur:
            # Check tables
            cur.execute("""
                SELECT table_name FROM information_schema.tables
                WHERE table_schema = 'public'
            """)
            tables = [row[0] for row in cur.fetchall()]
            expected_tables = ['customers', 'products', 'orders', 'order_items', 'reviews']
            
            missing_tables = set(expected_tables) - set(tables)
            if missing_tables:
                errors.append(f"Missing tables: {missing_tables}")
            
            # Check row counts
            cur.execute("SELECT COUNT(*) FROM customers")
            if cur.fetchone()[0] != 500:
                errors.append("Expected 500 customers")
            
            cur.execute("SELECT COUNT(*) FROM orders")
            order_count = cur.fetchone()[0]
            if not (4900 <= order_count <= 5100):
                errors.append(f"Expected ~5000 orders, got {order_count}")
            
            # Check foreign key integrity
            cur.execute("""
                SELECT COUNT(*) FROM orders o
                WHERE NOT EXISTS (SELECT 1 FROM customers c WHERE c.id = o.customer_id)
            """)
            if cur.fetchone()[0] > 0:
                errors.append("Orphaned orders (invalid customer_id)")
            
            # Check indexes
            cur.execute("""
                SELECT indexname FROM pg_indexes
                WHERE schemaname = 'public' AND tablename = 'orders'
            """)
            index_names = [row[0] for row in cur.fetchall()]
            expected_indexes = ['idx_orders_customer_id', 'idx_orders_order_date']
            missing_indexes = set(expected_indexes) - set(index_names)
            if missing_indexes:
                errors.append(f"Missing indexes: {missing_indexes}")
    
    return errors

def verify_role(config: Config) -> list[str]:
    """Verify read-only role exists and has correct permissions."""
    errors = []
    
    try:
        with psycopg.connect(config.target_db_url) as conn:
            with conn.cursor() as cur:
                # Check role exists
                cur.execute(f"""
                    SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname = '{config.target_db_readonly_role}')
                """)
                if not cur.fetchone()[0]:
                    errors.append(f"Role {config.target_db_readonly_role} does not exist")
                
                # Try SELECT (should succeed)
                cur.execute("SET ROLE querypilot_ro; SELECT COUNT(*) FROM customers;")
                
                # Try INSERT (should fail)
                try:
                    cur.execute("INSERT INTO customers (name, email, state, region) VALUES ('test', 'test@test.com', 'CA', 'West');")
                    errors.append(f"Role {config.target_db_readonly_role} has INSERT permission (should be denied!)")
                except psycopg.errors.InsufficientPrivilege:
                    pass  # Expected
    except Exception as e:
        errors.append(f"Role verification failed: {e}")
    
    return errors

def main():
    """Run all verification checks."""
    try:
        config = Config()
    except ValueError as e:
        print(f"✗ Configuration error: {e}")
        return 1
    
    all_errors = []
    
    print("Verifying Target DB schema...")
    errors = verify_schema(config)
    if errors:
        all_errors.extend(errors)
        for error in errors:
            print(f"  ✗ {error}")
    else:
        print("  ✓ Schema verified")
    
    print("Verifying read-only role...")
    errors = verify_role(config)
    if errors:
        all_errors.extend(errors)
        for error in errors:
            print(f"  ✗ {error}")
    else:
        print("  ✓ Role verified")
    
    if all_errors:
        print(f"\n✗ {len(all_errors)} check(s) failed")
        return 1
    else:
        print("\n✓ All checks passed")
        return 0

if __name__ == "__main__":
    sys.exit(main())
```

### `app.verify_llm`: LLM Client Verification

**File: `app/verify_llm.py`**

```python
import sys
from app.config import Config
from eval.baseline import get_llm_client

def verify_llm():
    """Verify LLM client is configured and working."""
    try:
        config = Config()
    except ValueError as e:
        print(f"✗ Configuration error: {e}")
        return 1
    
    print(f"Verifying LLM provider: {config.llm_provider}")
    
    try:
        llm_client = get_llm_client(config)
        print(f"  ✓ Client instantiated: {llm_client}")
    except Exception as e:
        print(f"  ✗ Failed to instantiate client: {e}")
        return 1
    
    print(f"Testing LLM call with model: {config.llm_model}")
    try:
        response = llm_client.call("Write the SQL: SELECT 1;")
        if response:
            print(f"  ✓ LLM responded (length: {len(response)} chars)")
        else:
            print(f"  ✗ LLM returned empty response")
            return 1
    except Exception as e:
        print(f"  ✗ LLM call failed: {e}")
        return 1
    
    print("\n✓ All LLM checks passed")
    return 0

if __name__ == "__main__":
    sys.exit(verify_llm())
```

### Exit Codes

- **0**: All checks passed
- **1**: Any check failed

---

## 11. File Structure & Artifacts

### Core Files

```
seed/
  ├── schema.sql                 # DDL: 5 tables + querypilot_ro role
  ├── generator.py               # DataGenerator class (deterministic seeding)
  ├── verify.py                  # Verification script (row counts, FK integrity)
  └── __init__.py

eval/
  ├── baseline.py                # LLMClient interface + concrete implementations + baseline_text_to_sql()
  ├── dataset.jsonl              # 20 evaluation items (JSONL format)
  ├── run_eval.py                # Main evaluation runner (--baseline flag)
  ├── metrics.py                 # Accuracy computation, result comparison
  ├── baseline_results.json      # Output: detailed results (generated after run_eval)
  └── __init__.py

app/
  ├── config.py                  # Pydantic BaseSettings (env var configuration)
  ├── verify_llm.py              # LLM client verification script
  └── main.py                    # (FastAPI entry, outside scope of this design)

.env.example                      # Environment variable documentation (version-controlled)
docker-compose.yml               # Docker services: target_db, app_db
```

### Supporting Files (Auto-Generated)

```
eval/
  └── baseline_results.json      # Generated after run_eval (not version-controlled)
```

---

## 12. Data Flow Diagrams

### Initialization Flow

```
User runs: docker-compose up -d

┌─────────────────────────────────────────────────────────────────┐
│ docker-compose reads .env for env vars                           │
└──────────────────────┬──────────────────────────────────────────┘
                       │
       ┌───────────────┴───────────────┐
       │                               │
       ▼                               ▼
   target_db                        app_db
   service                          service
   │                                │
   ├─ Start PostgreSQL              ├─ Start PostgreSQL
   │  process                        │  process
   │                                 │
   ├─ Run init script:              ├─ Run init script:
   │  /docker-entrypoint-            │  /docker-entrypoint-
   │   initdb.d/01-schema.sql        │   initdb.d/01-app-
   │  ├─ CREATE 5 tables             │   schema.sql
   │  ├─ CREATE indexes              │  ├─ CREATE conversations
   │  ├─ CREATE querypilot_ro        │  ├─ CREATE query_log
   │  └─ GRANT SELECT                │  ├─ CREATE eval_runs
   │                                 │
   ├─ Run post-init:                │
   │  seed/generator.py             │
   │  ├─ Generate 500 customers     │
   │  ├─ Generate 50 products       │
   │  ├─ Generate 5000 orders       │
   │  ├─ Generate 20k+ order_items  │
   │  ├─ Generate 1.2k reviews      │
   │  └─ INSERT all data (batches)  │
   │                                 │
   ├─ Health check loop:            ├─ Health check loop:
   │  pg_isready every 5s            │  pg_isready every 5s
   │  (5 retries)                    │  (5 retries)
   │                                 │
   └─ Status: Ready                 └─ Status: Ready

Both services healthy ──► docker-compose up completes successfully
```

### Baseline Evaluation Flow

```
User runs: python -m eval.run_eval --baseline

┌──────────────────────────────────────────┐
│ Load configuration from .env             │
│ (TARGET_DB_URL, LLM_PROVIDER, etc.)      │
└──────────────┬───────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────┐
│ Load eval/dataset.jsonl (20 items)       │
└──────────────┬───────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────┐
│ Instantiate LLM client (factory)         │
│ (OpenAI, Anthropic, or Bedrock)         │
└──────────────┬───────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────┐
│ For each of 20 items:                    │
│                                          │
│ 1. Extract question from item            │
│                                          │
│ 2. Fetch Target DB schema                │
│    (SELECT FROM information_schema)      │
│                                          │
│ 3. Construct prompt                      │
│    schema + context + question           │
│                                          │
│ 4. Call LLM client                       │
│    (OpenAI API / Anthropic API / Bedrock)
│                                          │
│ 5. Extract SQL from response             │
│    (remove markdown code blocks)         │
│                                          │
│ 6. Execute generated SQL                 │
│    (Target DB, querypilot_ro role)       │
│    (5s timeout, 1000 row limit)          │
│                                          │
│ 7. Execute gold SQL                      │
│    (Target DB, same params)              │
│                                          │
│ 8. Compare result sets                   │
│    (order-insensitive)                   │
│                                          │
│ 9. Log item result to App DB             │
│    (query_log table)                     │
│                                          │
│ 10. Record item result:                  │
│     ├─ question                          │
│     ├─ generated_sql                     │
│     ├─ gold_sql                          │
│     ├─ match (true/false)                │
│     └─ error (if any)                    │
└──────────────┬───────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────┐
│ Compute metrics:                         │
│ ├─ Overall accuracy (matches / 20)       │
│ ├─ Category breakdown                    │
│ ├─ Error rate                            │
│ └─ Error breakdown by type               │
└──────────────┬───────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────┐
│ Log full run to App DB                   │
│ (eval_runs table with results JSON)      │
└──────────────┬───────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────┐
│ Print summary to stdout                  │
│ (accuracy %, category breakdown, etc.)   │
└──────────────┬───────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────┐
│ Save detailed report to                  │
│ eval/baseline_results.json               │
└──────────────────────────────────────────┘
```

### Configuration Flow

```
.env file (version-controlled placeholder)
   │
   ├─ TARGET_DB_URL=postgresql://...
   ├─ LLM_PROVIDER=openai
   ├─ OPENAI_API_KEY=sk-...
   └─ ...

         ▼
┌────────────────────────────────────┐
│ Pydantic BaseSettings              │
│ (app/config.py)                    │
│                                    │
│ Reads .env and env vars            │
│ Validates required fields          │
│ Provides typed Config object       │
└────────────┬───────────────────────┘
             │
    ┌────────┴─────────┬──────────────┬───────────────┐
    │                  │              │               │
    ▼                  ▼              ▼               ▼
Database Conn   LLM Client Factory  Query Limits  Debug Flag
```

---

## 13. Error Handling & Edge Cases

### Error Types and Handling

| Error Type | Source | Handling | Logging |
|---|---|---|---|
| **LLMError (auth)** | LLM API returns 401/403 | Raise LLMError, stop item | Log: provider, category, skip item |
| **LLMError (rate limit)** | LLM API returns 429 | Raise LLMError, stop item | Log: provider, rate limit hit, skip |
| **LLMError (timeout)** | LLM API call >30s | Raise LLMError, stop item | Log: provider, timeout, skip |
| **InvalidResponseError** | LLM response has no SQL | Raise error, stop item | Log: response too short, skip |
| **ExecutionError (syntax)** | Generated SQL has syntax error | Catch psycopg.errors.SyntaxError | Log: error type, skip item, mark as error |
| **ExecutionError (timeout)** | Query runs >5s | Catch psycopg.errors.OperationalError | Log: timeout, skip item |
| **ExecutionError (runtime)** | Division by zero, column not found, etc. | Catch Exception | Log: error type, skip item |
| **ConfigError (missing var)** | Required env var not set | Raise ConfigError at startup | Print error, exit 1 |
| **Result mismatch** | Row counts or values differ | Record as false match | Log: mismatch reason |

### Edge Cases

1. **Empty result set (generated SQL returns 0 rows, gold returns 0 rows)**
   - ✓ Handled: Considered a match (both empty)

2. **NULL values in results**
   - ✓ Handled: Included in comparison (NULL == NULL in sets)

3. **Ambiguous gold SQL interpretation**
   - ✓ Handled: Gold SQL is documented with comment; one interpretation is canonical

4. **Column order differs between generated and gold**
   - ✓ Handled: Comparison uses column names (dict keys), not order

5. **Row order differs (no ORDER BY in query)**
   - ✓ Handled: Order-insensitive comparison by default

6. **LLM returns markdown-formatted SQL**
   - ✓ Handled: extract_sql() removes code block markers

7. **LLM returns multiple SQL statements (semicolon-separated)**
   - ✗ Not handled in baseline: Only first statement is attempted; error logged

8. **Database connection pool exhausted**
   - ✓ Handled: psycopg connection pool has limits; errors caught generically

9. **Target DB is offline**
   - ✓ Handled: psycopg.errors.OperationalError caught, logged as error

---

## 14. Security Considerations

### Read-Only Role Enforcement

- **Role creation:** `CREATE ROLE querypilot_ro NOLOGIN;`
- **Grants:** `GRANT SELECT ON ALL TABLES IN SCHEMA public TO querypilot_ro;`
- **Revokes:** `REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON ALL TABLES FROM querypilot_ro;`
- **Per-query:** `SET TRANSACTION READ ONLY;` at start of every session
- **Verification:** Unit test attempts INSERT (must fail with InsufficientPrivilege)

### Credentials and Secrets

- **Never hardcode** API keys, DB passwords, or auth tokens in source code
- **Read from env vars only** via `pydantic-settings`
- **Never log** credentials or sensitive response data
- **Mask in logs** database URLs, API keys (if accidentally logged)

### Query Timeout and Row Limits

- **Timeout:** `SET statement_timeout = 5000;` (milliseconds) prevents runaway queries
- **Row limit:** Fetch max 1,000 rows to prevent memory exhaustion
- **Both enforce database-level** (not application-level only)

---

## 15. Performance & Scalability

### Execution Time Estimates

| Component | Time | Notes |
|---|---|---|
| Docker startup (both DBs) | 10–20s | Health checks + data initialization |
| Data generation (5k orders) | ~5–10s | Deterministic seeding, batched inserts |
| Schema fetch (from information_schema) | ~100ms | Single SELECT query |
| LLM call (OpenAI/Anthropic) | 1–3s | Network latency + model inference |
| SQL execution (generated or gold) | 100–500ms | Depends on query complexity |
| Result comparison | <10ms | In-memory set operations |
| Full evaluation run (20 items) | ~3–5 min | 20 × (1–3s LLM + 100–500ms exec + compare) |

### Scalability Considerations

- **Data volume:** 500 customers, 5k orders is small; scales easily to 50k+ orders if needed
- **LLM call parallelization:** Baseline runs sequentially (not parallelized in initial phase)
- **Database connections:** Connection pooling via psycopg (default: 10 connections)
- **Row limits:** 1,000 row fetch limit prevents memory bloat even for large result sets

---

## 16. Testing Strategy

### Unit Tests

**`tests/tools/test_validator.py`** (out of scope for baseline but outlined):
- Verify sqlglot parsing (future validation layer)

**`tests/tools/test_executor.py`:**
- Test execute_sql() with timeout
- Test row limit enforcement
- Test read-only transaction enforcement

**`tests/tools/test_schema.py`:**
- Test schema fetch from information_schema

### Integration Tests

**`tests/eval/test_baseline.py`:**
- Test LLMClient instantiation (each provider)
- Test baseline_text_to_sql() with mock LLM
- Test extract_sql() with various markdown formats
- Test result comparison (order-insensitive, NULL handling)

### Smoke Test (Manual)

```bash
# 1. Start services
docker-compose up -d

# 2. Verify schema
python -m seed.verify

# 3. Verify LLM
python -m app.verify_llm

# 4. Run baseline
python -m eval.run_eval --baseline

# 5. Check results
cat eval/baseline_results.json
```

---

## 17. Decisions & Rationale

### Decision 1: Deterministic Seeding (seed=42)

**Rationale:** Reproducibility across environments and iterations; same seed = identical data enables reliable A/B comparison of agent improvements.

**Alternative rejected:** Random seeding would produce different data each run, making it hard to isolate LLM performance from data variance.

### Decision 2: Separate Target DB and App DB

**Rationale:** Separation of concerns; target DB is read-only production-like data, app DB stores QueryPilot metadata. Prevents accidental data pollution.

**Alternative rejected:** Single database would be simpler but conflates concerns and adds risk.

### Decision 3: Abstract LLM Interface with Factory Pattern

**Rationale:** Flexibility to swap providers (OpenAI → Anthropic → Bedrock) without code changes; only env var changes. Easier testing and mocking.

**Alternative rejected:** Hard-code one provider would be simpler but less flexible.

### Decision 4: Single-Call Baseline (No Retry, No Validation)

**Rationale:** Measure naive performance; provides quantitative "before" reference. Later phases add validation, retry loops, and memory.

**Alternative rejected:** Validating generated SQL in baseline would inflate accuracy and hide true LLM limitations.

### Decision 5: 20-Item Evaluation Dataset

**Rationale:** Small enough for quick iteration (~3–5 min per run), large enough to show category breakdown (5 items per category). Can be expanded to 100+ later.

**Alternative rejected:** 100+ items would be more statistically robust but slower to iterate; 5–10 items would be too noisy.

### Decision 6: JSONL Format for Dataset

**Rationale:** Simple line-delimited JSON; easy to stream, version-control, and extend. Each line is self-contained.

**Alternative rejected:** CSV would be less flexible for nested structures (expected_tables list); SQL files would be harder to parse programmatically.

### Decision 7: Order-Insensitive Result Comparison

**Rationale:** Most business queries don't specify ORDER BY; result order is unpredictable. Comparing unordered sets is more robust.

**Alternative rejected:** Strict ordering would incorrectly mark equivalent results as mismatches.

---

## Summary

This design document specifies the end-to-end architecture for the **seed-db-baseline** spec:

1. **Schema & Data:** 5-table e-commerce schema with 500 customers, 5k orders, deterministically seeded for reproducibility.
2. **Security:** Read-only PostgreSQL role (`querypilot_ro`) with SELECT-only permissions, enforced per-query via `SET TRANSACTION READ ONLY`.
3. **Docker:** Two PostgreSQL services (target_db, app_db) initialized and healthchecked.
4. **LLM Client:** Swappable interface supporting OpenAI, Anthropic, Bedrock; provider selected via `LLM_PROVIDER` env var.
5. **Baseline Function:** Single-call text-to-SQL function sends schema + question to LLM, extracts SQL, returns as-is (no validation).
6. **Evaluation:** 20-item JSONL dataset with balanced categories; runs baseline against all items, compares results to gold SQL, computes accuracy metrics.
7. **Configuration:** All config via environment variables using Pydantic BaseSettings; `.env.example` documents all vars.
8. **Verification:** Health checks for database schema, data integrity, role permissions, and LLM client connectivity.

The design prioritizes **determinism, security, extensibility, and measurability** to establish a solid foundation for the full text-to-SQL agent build-out.
