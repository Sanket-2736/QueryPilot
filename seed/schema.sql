-- E-commerce sample schema for QueryPilot
-- Target database schema for text-to-SQL evaluation
-- This schema is used for the baseline evaluation harness

-- Customers table: base customer dimension
CREATE TABLE customers (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    email VARCHAR(255) NOT NULL UNIQUE,
    state VARCHAR(2) NOT NULL,
    region VARCHAR(50) NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

COMMENT ON TABLE customers IS 'Base customer dimension; one row per unique customer.';
COMMENT ON COLUMN customers.id IS 'Unique customer identifier.';
COMMENT ON COLUMN customers.name IS 'Full name of customer (synthetic, no PII).';
COMMENT ON COLUMN customers.email IS 'Unique email address (synthetic).';
COMMENT ON COLUMN customers.state IS 'Two-letter US state code (e.g., CA, NY, TX).';
COMMENT ON COLUMN customers.region IS 'Geographic region derived from state (e.g., West, Northeast).';
COMMENT ON COLUMN customers.created_at IS 'System timestamp when customer was created.';

-- Products table: product catalog
CREATE TABLE products (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    category VARCHAR(100) NOT NULL,
    price DECIMAL(10, 2) NOT NULL,
    stock_quantity INT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

COMMENT ON TABLE products IS 'Product catalog; one row per unique product SKU.';
COMMENT ON COLUMN products.id IS 'Unique product identifier.';
COMMENT ON COLUMN products.name IS 'Product name.';
COMMENT ON COLUMN products.category IS 'Product category for segmentation (e.g., Electronics, Apparel, Home, Books, Sports).';
COMMENT ON COLUMN products.price IS 'List price in USD.';
COMMENT ON COLUMN products.stock_quantity IS 'Current inventory count.';
COMMENT ON COLUMN products.created_at IS 'System timestamp when product was added to catalog.';

-- Orders table: transaction fact table
CREATE TABLE orders (
    id SERIAL PRIMARY KEY,
    customer_id INT NOT NULL REFERENCES customers(id) ON DELETE RESTRICT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    order_date DATE NOT NULL,
    status VARCHAR(50) NOT NULL CHECK (status IN ('paid', 'refunded', 'cancelled')),
    total_amount DECIMAL(10, 2) NOT NULL
);

COMMENT ON TABLE orders IS 'Order transactions; one row per customer order. Time-series fact table.';
COMMENT ON COLUMN orders.id IS 'Unique order identifier.';
COMMENT ON COLUMN orders.customer_id IS 'Foreign key to customers.id; which customer placed this order.';
COMMENT ON COLUMN orders.created_at IS 'System timestamp when order record was created.';
COMMENT ON COLUMN orders.order_date IS 'Date when order was placed (for time-series queries, business date).';
COMMENT ON COLUMN orders.status IS 'Order fulfillment status: paid (fulfilled), refunded (money back), cancelled (not fulfilled).';
COMMENT ON COLUMN orders.total_amount IS 'Gross total amount in USD; equals SUM of order_items.unit_price * quantity.';

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
COMMENT ON COLUMN order_items.unit_price IS 'Price per unit at time of order (may differ from products.price due to discounts).';
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

COMMENT ON TABLE reviews IS 'Customer product reviews; one row per review.';
COMMENT ON COLUMN reviews.id IS 'Unique review identifier.';
COMMENT ON COLUMN reviews.product_id IS 'Foreign key to products.id; which product is reviewed.';
COMMENT ON COLUMN reviews.customer_id IS 'Foreign key to customers.id; which customer wrote the review.';
COMMENT ON COLUMN reviews.rating IS 'Star rating: 1 (poor) to 5 (excellent).';
COMMENT ON COLUMN reviews.comment IS 'Optional text feedback.';
COMMENT ON COLUMN reviews.created_at IS 'System timestamp when review was created.';

-- Indexes for query performance
CREATE INDEX idx_orders_customer_id ON orders(customer_id);
CREATE INDEX idx_orders_order_date ON orders(order_date);
CREATE INDEX idx_order_items_order_id ON order_items(order_id);
CREATE INDEX idx_order_items_product_id ON order_items(product_id);
CREATE INDEX idx_reviews_product_id ON reviews(product_id);
CREATE INDEX idx_reviews_customer_id ON reviews(customer_id);

-- Create read-only role and grant permissions
-- This role is used by the QueryPilot application for safe, read-only queries
CREATE ROLE querypilot_ro WITH LOGIN PASSWORD 'readonly_password';
GRANT SELECT ON ALL TABLES IN SCHEMA public TO querypilot_ro;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO querypilot_ro;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON ALL TABLES IN SCHEMA public FROM querypilot_ro;

-- Prevent writes at transaction level (defense in depth)
-- This is set at connection time in the application
ALTER ROLE querypilot_ro SET statement_timeout = '5s';
