-- Example queries to demonstrate pg_plan_alternatives
-- Run these queries while tracing with pg_plan_alternatives

-- Setup: Create test tables
CREATE TABLE IF NOT EXISTS customers (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100),
    email VARCHAR(100),
    city VARCHAR(50)
);

CREATE TABLE IF NOT EXISTS orders (
    id SERIAL PRIMARY KEY,
    customer_id INTEGER REFERENCES customers(id),
    order_date DATE,
    amount DECIMAL(10,2)
);

-- Insert sample data
INSERT INTO customers (name, email, city)
SELECT 
    'Customer ' || i,
    'customer' || i || '@example.com',
    CASE (i % 5)
        WHEN 0 THEN 'New York'
        WHEN 1 THEN 'Los Angeles'
        WHEN 2 THEN 'Chicago'
        WHEN 3 THEN 'Houston'
        ELSE 'Phoenix'
    END
FROM generate_series(1, 1000) i
ON CONFLICT DO NOTHING;

INSERT INTO orders (customer_id, order_date, amount)
SELECT 
    (random() * 999 + 1)::INTEGER,
    CURRENT_DATE - (random() * 365)::INTEGER,
    (random() * 1000)::DECIMAL(10,2)
FROM generate_series(1, 10000)
ON CONFLICT DO NOTHING;

-- Create indexes
CREATE INDEX IF NOT EXISTS idx_customers_city ON customers(city);
CREATE INDEX IF NOT EXISTS idx_orders_customer ON orders(customer_id);
CREATE INDEX IF NOT EXISTS idx_orders_date ON orders(order_date);

-- Analyze tables
ANALYZE customers;
ANALYZE orders;

-- Example 1: Simple query with index vs sequential scan
SELECT * FROM customers WHERE city = 'New York';

-- Example 2: Range query
SELECT * FROM orders WHERE order_date BETWEEN '2023-01-01' AND '2023-12-31';

-- Example 3: Join query (will show different join strategies)
SELECT c.name, COUNT(*) as order_count, SUM(o.amount) as total_amount
FROM customers c
JOIN orders o ON c.id = o.customer_id
WHERE c.city = 'Chicago'
GROUP BY c.name
HAVING COUNT(*) > 5;

-- Example 4: Complex query with multiple joins
SELECT 
    c.city,
    COUNT(DISTINCT c.id) as customer_count,
    COUNT(o.id) as order_count,
    AVG(o.amount) as avg_order_amount
FROM customers c
LEFT JOIN orders o ON c.id = o.customer_id
GROUP BY c.city
ORDER BY customer_count DESC;

-- Example 5: Subquery (will show SubqueryScanPath)
SELECT name, email
FROM customers
WHERE id IN (
    SELECT customer_id
    FROM orders
    WHERE amount > 500
    GROUP BY customer_id
    HAVING COUNT(*) > 3
);
