"""Verification script for database schema, data, and role configuration."""

import sys
import psycopg
from app.config import get_config


def verify_schema(config) -> list[str]:
    """Verify Target DB schema is correct.

    Args:
        config: Configuration object

    Returns:
        List of error messages (empty if all checks pass)
    """
    errors = []

    try:
        with psycopg.connect(config.target_db_url) as conn:
            with conn.cursor() as cur:
                # Check tables exist
                cur.execute("""
                    SELECT table_name FROM information_schema.tables
                    WHERE table_schema = 'public'
                    ORDER BY table_name
                """)
                tables = [row[0] for row in cur.fetchall()]
                expected_tables = {"customers", "products", "orders", "order_items", "reviews"}

                missing_tables = expected_tables - set(tables)
                if missing_tables:
                    errors.append(f"Missing tables: {missing_tables}")

                # Check row counts
                cur.execute("SELECT COUNT(*) FROM customers")
                customer_count = cur.fetchone()[0]
                if customer_count != 500:
                    errors.append(f"Expected 500 customers, got {customer_count}")

                cur.execute("SELECT COUNT(*) FROM products")
                product_count = cur.fetchone()[0]
                if product_count != 50:
                    errors.append(f"Expected 50 products, got {product_count}")

                cur.execute("SELECT COUNT(*) FROM orders")
                order_count = cur.fetchone()[0]
                if not (4900 <= order_count <= 5100):
                    errors.append(f"Expected ~5000 orders, got {order_count}")

                # Check foreign key integrity (no orphaned rows)
                cur.execute("""
                    SELECT COUNT(*) FROM orders o
                    WHERE NOT EXISTS (SELECT 1 FROM customers c WHERE c.id = o.customer_id)
                """)
                orphaned_orders = cur.fetchone()[0]
                if orphaned_orders > 0:
                    errors.append(f"Found {orphaned_orders} orphaned orders (invalid customer_id)")

                cur.execute("""
                    SELECT COUNT(*) FROM order_items oi
                    WHERE NOT EXISTS (SELECT 1 FROM orders o WHERE o.id = oi.order_id)
                """)
                orphaned_items = cur.fetchone()[0]
                if orphaned_items > 0:
                    errors.append(f"Found {orphaned_items} orphaned order_items (invalid order_id)")

                # Check indexes
                cur.execute("""
                    SELECT indexname FROM pg_indexes
                    WHERE schemaname = 'public'
                    ORDER BY indexname
                """)
                index_names = {row[0] for row in cur.fetchall()}
                expected_indexes = {
                    "idx_orders_customer_id",
                    "idx_orders_order_date",
                    "idx_order_items_order_id",
                    "idx_order_items_product_id",
                    "idx_reviews_product_id",
                    "idx_reviews_customer_id",
                }
                missing_indexes = expected_indexes - index_names
                if missing_indexes:
                    errors.append(f"Missing indexes: {missing_indexes}")

    except psycopg.Error as e:
        errors.append(f"Database error: {e}")

    return errors


def verify_role(config) -> list[str]:
    """Verify read-only role exists and has correct permissions.

    Args:
        config: Configuration object

    Returns:
        List of error messages (empty if all checks pass)
    """
    errors = []

    try:
        with psycopg.connect(config.target_db_url) as conn:
            with conn.cursor() as cur:
                # Check role exists
                cur.execute(f"""
                    SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname = '{config.target_db_readonly_role}')
                """)
                if not cur.fetchone()[0]:
                    errors.append(f"Role '{config.target_db_readonly_role}' does not exist")
                    return errors  # Can't test permissions if role doesn't exist

                # Try SELECT (should succeed)
                try:
                    cur.execute(f"SET ROLE {config.target_db_readonly_role}")
                    cur.execute("SELECT COUNT(*) FROM customers")
                    _ = cur.fetchone()
                except psycopg.Error as e:
                    errors.append(f"SELECT on {config.target_db_readonly_role} failed: {e}")

                # Reset to default role
                cur.execute("RESET ROLE")

                # Try INSERT (should fail with permission denied)
                try:
                    cur.execute(f"SET ROLE {config.target_db_readonly_role}")
                    cur.execute(
                        "INSERT INTO customers (name, email, state, region) VALUES (%s, %s, %s, %s)",
                        ("test", "test@test.com", "CA", "West"),
                    )
                    errors.append(
                        f"Role {config.target_db_readonly_role} has INSERT permission (should be denied!)"
                    )
                except psycopg.errors.InsufficientPrivilege:
                    pass  # Expected
                except psycopg.Error as e:
                    errors.append(f"Unexpected error on INSERT test: {e}")
                finally:
                    cur.execute("RESET ROLE")

    except psycopg.Error as e:
        errors.append(f"Role verification failed: {e}")

    return errors


def main() -> int:
    """Run all verification checks.

    Returns:
        0 if all checks pass, 1 if any check fails
    """
    try:
        config = get_config()
    except ValueError as e:
        print(f"✗ Configuration error: {e}")
        return 1

    print("=" * 80)
    print("Database Verification")
    print("=" * 80)

    all_errors = []

    # Verify schema
    print("\n1. Verifying schema...")
    errors = verify_schema(config)
    if errors:
        all_errors.extend(errors)
        for error in errors:
            print(f"   ✗ {error}")
    else:
        print("   ✓ Schema verified (5 tables, correct row counts, FK integrity, indexes)")

    # Verify role
    print("\n2. Verifying read-only role...")
    errors = verify_role(config)
    if errors:
        all_errors.extend(errors)
        for error in errors:
            print(f"   ✗ {error}")
    else:
        print(f"   ✓ Role '{config.target_db_readonly_role}' verified (SELECT OK, INSERT denied)")

    print("\n" + "=" * 80)
    if all_errors:
        print(f"✗ {len(all_errors)} check(s) failed")
        print("=" * 80)
        return 1
    else:
        print("✓ All checks passed")
        print("=" * 80)
        return 0


if __name__ == "__main__":
    sys.exit(main())
