"""Deterministic synthetic data generator for e-commerce schema.

Generates realistic synthetic customer, product, order, and review data
with fixed random seed (default: 42) for reproducibility across runs and environments.
"""

import random
from datetime import datetime, timedelta
from typing import Generator, Optional, Any
import psycopg


class DataGenerator:
    """Generate deterministic synthetic e-commerce data."""

    # Sample data for deterministic generation
    FIRST_NAMES = [
        "John", "Jane", "Bob", "Alice", "Charlie", "Diana", "Eve", "Frank",
        "Grace", "Henry", "Ivy", "Jack", "Kate", "Liam", "Mia", "Noah",
        "Olivia", "Peter", "Quinn", "Rachel", "Sam", "Tina", "Uma", "Victor"
    ]

    LAST_NAMES = [
        "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller",
        "Davis", "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez",
        "Wilson", "Anderson", "Thomas", "Taylor", "Moore", "Jackson", "Martin"
    ]

    STATES = ["CA", "NY", "TX", "FL", "PA", "IL", "OH", "GA", "NC", "MI"]

    REGIONS = {
        "CA": "West", "WA": "West", "OR": "West",
        "NV": "West", "AZ": "West", "HI": "West",
        "NY": "Northeast", "PA": "Northeast", "NJ": "Northeast",
        "CT": "Northeast", "MA": "Northeast", "VT": "Northeast",
        "TX": "South", "FL": "South", "GA": "South", "NC": "South",
        "SC": "South", "VA": "South", "MD": "South",
        "IL": "Midwest", "OH": "Midwest", "MI": "Midwest",
        "IN": "Midwest", "WI": "Midwest", "MN": "Midwest",
    }

    CATEGORIES = ["Electronics", "Apparel", "Home", "Books", "Sports"]

    COMMENTS = [
        "Great product!", "Excellent quality.", "Highly recommend.",
        "Good value for money.", "Very satisfied.", "As described.",
        "Not bad.", "Could be better.", "Disappointed.", "Amazing!",
        "Love it!", "Perfect.", "Outstanding.", "Fantastic.",
    ]

    def __init__(self, seed: int = 42, conn_str: Optional[str] = None):
        """Initialize data generator with deterministic seed.

        Args:
            seed: Random seed for reproducibility (default: 42)
            conn_str: PostgreSQL connection string (optional, set later)
        """
        self.seed = seed
        self.conn_str = conn_str
        random.seed(seed)

    def generate_customers(self, count: int = 500) -> Generator[dict[str, Any], None, None]:
        """Generate synthetic customer records.

        Args:
            count: Number of customers to generate (default: 500)

        Yields:
            Dict with keys: name, email, state, region, created_at
        """
        for i in range(count):
            first_name = self.FIRST_NAMES[i % len(self.FIRST_NAMES)]
            last_idx = (i // len(self.FIRST_NAMES)) % len(self.LAST_NAMES)
            last_name = self.LAST_NAMES[last_idx]
            full_name = f"{first_name} {last_name}"

            email = f"{full_name.lower().replace(' ', '.')}.{random.randint(1000, 9999)}@example.com"
            state = random.choice(self.STATES)
            region = self.REGIONS.get(state, "Other")

            yield {
                "name": full_name,
                "email": email,
                "state": state,
                "region": region,
                "created_at": self._random_datetime_in_2024(),
            }

    def generate_products(self, count: int = 50) -> Generator[dict[str, Any], None, None]:
        """Generate synthetic product records.

        Args:
            count: Number of products to generate (default: 50)

        Yields:
            Dict with keys: name, category, price, stock_quantity, created_at
        """
        for i in range(count):
            yield {
                "name": f"Product {i+1}",
                "category": random.choice(self.CATEGORIES),
                "price": round(random.uniform(10, 500), 2),
                "stock_quantity": random.randint(0, 1000),
                "created_at": self._random_datetime_in_2024(),
            }

    def generate_orders(
        self, count: int = 5000, num_customers: int = 500
    ) -> Generator[dict[str, Any], None, None]:
        """Generate synthetic order records with Pareto distribution.

        ~60% in 2024, ~40% in 2025 to show year-over-year growth.

        Args:
            count: Number of orders to generate (default: 5000)
            num_customers: Number of customers (for customer_id range)

        Yields:
            Dict with keys: customer_id, order_date, status, total_amount
        """
        for _ in range(count):
            # Pareto distribution: some customers have many orders, most have few
            # pareto(alpha) generates values from 1 to infinity; we scale to customer range
            pareto_val = random.paretovariate(1.5)
            customer_id = max(1, min(int(pareto_val) % num_customers + 1, num_customers))

            # Temporal: 60% 2024, 40% 2025
            if random.random() < 0.6:
                order_date = self._random_date_in_2024()
            else:
                order_date = self._random_date_in_2025()

            # Status distribution: 85% paid, 10% refunded, 5% cancelled
            status = random.choices(
                ["paid", "refunded", "cancelled"],
                weights=[85, 10, 5]
            )[0]

            total_amount = round(random.uniform(20, 2000), 2)

            yield {
                "customer_id": customer_id,
                "order_date": order_date,
                "status": status,
                "total_amount": total_amount,
            }

    def generate_order_items(
        self, order_ids: list[int], num_products: int = 50
    ) -> Generator[dict[str, Any], None, None]:
        """Generate 3-5 line items per order.

        Args:
            order_ids: List of order IDs to associate items with
            num_products: Number of products (for product_id range)

        Yields:
            Dict with keys: order_id, product_id, quantity, unit_price
        """
        for order_id in order_ids:
            num_items = random.randint(3, 5)
            for _ in range(num_items):
                yield {
                    "order_id": order_id,
                    "product_id": random.randint(1, num_products),
                    "quantity": random.randint(1, 10),
                    "unit_price": round(random.uniform(10, 300), 2),
                }

    def generate_reviews(
        self, count: int = 1250, num_customers: int = 500, num_products: int = 50
    ) -> Generator[dict[str, Any], None, None]:
        """Generate review records.

        Args:
            count: Number of reviews to generate (default: 1250)
            num_customers: Number of customers (for customer_id range)
            num_products: Number of products (for product_id range)

        Yields:
            Dict with keys: product_id, customer_id, rating, comment
        """
        for _ in range(count):
            comment = random.choice(self.COMMENTS) if random.random() > 0.5 else None
            yield {
                "product_id": random.randint(1, num_products),
                "customer_id": random.randint(1, num_customers),
                "rating": random.randint(1, 5),
                "comment": comment,
            }

    def populate_database(self) -> None:
        """Execute generation and insert all data into database."""
        if not self.conn_str:
            raise ValueError("Connection string not set. Set conn_str before calling populate_database().")

        with psycopg.connect(self.conn_str) as conn:
            # Insert customers
            print("Generating and inserting customers...")
            customers = list(self.generate_customers(500))
            with conn.cursor() as cur:
                for c in customers:
                    cur.execute(
                        "INSERT INTO customers (name, email, state, region, created_at) VALUES (%s, %s, %s, %s, %s)",
                        (c["name"], c["email"], c["state"], c["region"], c["created_at"]),
                    )
            conn.commit()
            print(f"✓ Inserted {len(customers)} customers")

            # Insert products
            print("Generating and inserting products...")
            products = list(self.generate_products(50))
            with conn.cursor() as cur:
                for p in products:
                    cur.execute(
                        "INSERT INTO products (name, category, price, stock_quantity, created_at) VALUES (%s, %s, %s, %s, %s)",
                        (p["name"], p["category"], p["price"], p["stock_quantity"], p["created_at"]),
                    )
            conn.commit()
            print(f"✓ Inserted {len(products)} products")

            # Insert orders
            print("Generating and inserting orders...")
            orders = list(self.generate_orders(5000, 500))
            with conn.cursor() as cur:
                for o in orders:
                    cur.execute(
                        "INSERT INTO orders (customer_id, order_date, status, total_amount) VALUES (%s, %s, %s, %s)",
                        (o["customer_id"], o["order_date"], o["status"], o["total_amount"]),
                    )
            conn.commit()
            print(f"✓ Inserted {len(orders)} orders")

            # Fetch inserted order IDs for order_items
            with conn.cursor() as cur:
                cur.execute("SELECT id FROM orders ORDER BY id")
                order_ids = [row[0] for row in cur.fetchall()]

            # Insert order items
            print("Generating and inserting order items...")
            order_items = list(self.generate_order_items(order_ids, 50))
            with conn.cursor() as cur:
                for oi in order_items:
                    cur.execute(
                        "INSERT INTO order_items (order_id, product_id, quantity, unit_price) VALUES (%s, %s, %s, %s)",
                        (oi["order_id"], oi["product_id"], oi["quantity"], oi["unit_price"]),
                    )
            conn.commit()
            print(f"✓ Inserted {len(order_items)} order items")

            # Insert reviews
            print("Generating and inserting reviews...")
            reviews = list(self.generate_reviews(1250, 500, 50))
            with conn.cursor() as cur:
                for r in reviews:
                    cur.execute(
                        "INSERT INTO reviews (product_id, customer_id, rating, comment) VALUES (%s, %s, %s, %s)",
                        (r["product_id"], r["customer_id"], r["rating"], r["comment"]),
                    )
            conn.commit()
            print(f"✓ Inserted {len(reviews)} reviews")

    # Helper methods
    def _random_datetime_in_2024(self) -> datetime:
        """Generate random datetime in 2024."""
        start = datetime(2024, 1, 1)
        end = datetime(2024, 12, 31, 23, 59, 59)
        delta = end - start
        return start + timedelta(seconds=random.randint(0, int(delta.total_seconds())))

    def _random_date_in_2024(self) -> str:
        """Generate random date in 2024 (ISO format)."""
        dt = self._random_datetime_in_2024()
        return dt.date().isoformat()

    def _random_date_in_2025(self) -> str:
        """Generate random date in 2025 (ISO format)."""
        start = datetime(2025, 1, 1)
        end = datetime(2025, 12, 31, 23, 59, 59)
        delta = end - start
        dt = start + timedelta(seconds=random.randint(0, int(delta.total_seconds())))
        return dt.date().isoformat()


if __name__ == "__main__":
    # Entry point for docker-compose initialization
    import sys
    from app.config import get_config

    try:
        config = get_config()
        gen = DataGenerator(seed=42, conn_str=config.target_db_url)
        gen.populate_database()
        print("\n✓ Data generation complete!")
        sys.exit(0)
    except Exception as e:
        print(f"\n✗ Data generation failed: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)
