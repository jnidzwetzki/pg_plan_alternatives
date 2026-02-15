# Example Usage

This directory contains example queries and usage scenarios for pg_plan_alternatives.

## Basic Example

1. Start PostgreSQL and identify the backend PID:

```sql
SELECT pg_backend_pid();
```

2. In another terminal, start tracing:

```bash
sudo pg_plan_alternatives -x /usr/lib/postgresql/16/bin/postgres -p <PID> -j -o plans.json
```

3. Run a query in PostgreSQL:

```sql
-- Create a test table
CREATE TABLE test_table (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100),
    value INTEGER
);

-- Insert some data
INSERT INTO test_table (name, value)
SELECT 'name_' || i, i
FROM generate_series(1, 10000) i;

-- Create an index
CREATE INDEX idx_value ON test_table(value);

-- Analyze the table
ANALYZE test_table;

-- Run a query that could use multiple plans
SELECT * FROM test_table WHERE value = 5000;
```

4. View the results:

```bash
# View the JSON output
cat plans.json

# Create a visualization
visualize_plan_graph -i plans.json -o plans.html
```

## Example with Joins

```sql
-- Create two tables
CREATE TABLE customers (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100)
);

CREATE TABLE orders (
    id SERIAL PRIMARY KEY,
    customer_id INTEGER REFERENCES customers(id),
    amount DECIMAL(10,2)
);

-- Insert data
INSERT INTO customers (name)
SELECT 'Customer ' || i
FROM generate_series(1, 1000) i;

INSERT INTO orders (customer_id, amount)
SELECT 
    (random() * 999 + 1)::INTEGER,
    (random() * 1000)::DECIMAL(10,2)
FROM generate_series(1, 10000);

-- Create indexes
CREATE INDEX idx_orders_customer ON orders(customer_id);

-- Analyze
ANALYZE customers;
ANALYZE orders;

-- Run a join query
SELECT c.name, COUNT(*), SUM(o.amount)
FROM customers c
JOIN orders o ON c.id = o.customer_id
GROUP BY c.name
HAVING COUNT(*) > 5;
```

This will show various join strategies considered by PostgreSQL (nested loop, hash join, merge join).

## Expected Output

For the first query, you should see output like:

```
[14:23:45.123] [PID 1234] ADD_PATH: T_SeqScan (startup=0.00, total=173.00, rows=10000)
[14:23:45.124] [PID 1234] ADD_PATH: T_IndexPath (startup=0.42, total=8.44, rows=1)
[14:23:45.125] [PID 1234] CREATE_PLAN: T_IndexPath (startup=0.42, total=8.44) [CHOSEN]
```

This shows that PostgreSQL considered both a sequential scan and an index scan, but chose the index scan due to its lower total cost.
