# pg_plan_alternatives: A PostgreSQL Plan Alternatives Tracer
[![Basic Integration Tests](https://github.com/jnidzwetzki/pg_plan_alternatives/actions/workflows/integration_tests.yml/badge.svg)](https://github.com/jnidzwetzki/pg_plan_alternatives/actions/workflows/integration_tests.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![PyPI](https://img.shields.io/pypi/v/pg_plan_alternatives?color=green)](https://pypi.org/project/pg_plan_alternatives/)
[![PyPI - Downloads](https://img.shields.io/pypi/dm/pg-plan-alternatives)](https://pypi.org/project/pg_plan_alternatives/)
[![Release date](https://img.shields.io/github/release-date/jnidzwetzki/pg_plan_alternatives)](https://github.com/jnidzwetzki/pg_plan_alternatives/)
[![GitHub Repo stars](https://img.shields.io/github/stars/jnidzwetzki/pg_plan_alternatives?style=social)](https://github.com/jnidzwetzki/pg_plan_alternatives/)

An eBPF-based tool designed to show **all query plans** that are considered by PostgreSQL during query planning, not just the final chosen plan as shown in `EXPLAIN` output. 

## 🎯 Overview

PostgreSQL uses a cost-based optimizer to determine the most efficient way to execute a query. When PostgreSQL plans a query, it considers many different execution paths and chooses the one with the lowest estimated cost. The standard `EXPLAIN` command only shows the final chosen plan. `pg_plan_alternatives` reveals all the alternative plans that were considered, along with their costs, giving you a complete picture of the optimizer's reasoning.

Key features:
- **`pg_plan_alternatives`**: eBPF-based tracer that captures all query plans considered during planning
- **`visualize_plan_graph`**: Creates interactive graph visualizations from trace output
- Supports PostgreSQL 17 and 18
- JSON output format for easy processing
- Shows cost estimates (startup and total) for each alternative
- Highlights which plan was ultimately chosen

**Note:** This tool relies on [eBPF](https://ebpf.io/) (_Extended Berkeley Packet Filter_) technology and requires root privileges to run.

## ⚡ Quickstart

1. Install the tool:

```bash
pip install pg_plan_alternatives
```

2. Identify your PostgreSQL server binary (e.g., `/usr/lib/postgresql/17/bin/postgres`)

3. Start tracing (requires root privileges):

```bash
sudo pg_plan_alternatives -x /usr/lib/postgresql/17/bin/postgres -p <PID> -n $(pg_config --includedir-server)/nodes/nodetags.h
```

4. Run your queries in PostgreSQL

5. View the trace output showing all considered plans

## 📊 Usage Examples

### Basic Tracing

```bash
# Trace all PostgreSQL processes using the binary
sudo pg_plan_alternatives -x /usr/lib/postgresql/17/bin/postgres -n /path/to/nodetags.h

# Trace a specific PostgreSQL backend process
sudo pg_plan_alternatives -x /usr/lib/postgresql/17/bin/postgres -p 1234 -n /path/to/nodetags.h

# Trace multiple processes
sudo pg_plan_alternatives -x /usr/lib/postgresql/17/bin/postgres -p 1234 -p 5678 -n /path/to/nodetags.h

# Output in JSON format
sudo pg_plan_alternatives -x /usr/lib/postgresql/17/bin/postgres -p 1234 -j -n /path/to/nodetags.h

# Save output to file
sudo pg_plan_alternatives -x /usr/lib/postgresql/17/bin/postgres -p 1234 -j -o plans.json -n /path/to/nodetags.h

# Verbose mode
sudo pg_plan_alternatives -x /usr/lib/postgresql/17/bin/postgres -p 1234 -v -n /path/to/nodetags.h
```

*Note:* The path to `nodetags.h` is required to resolve the path type enums to human-readable names. 

### Creating Visualizations

```bash
# Create a PNG graph from trace output
visualize_plan_graph -i plans.json -o plans.png

# Create an interactive HTML visualization
visualize_plan_graph -i plans.json -o plans.html

# Create an SVG graph
visualize_plan_graph -i plans.json -o plans.svg

# Create separate graphs for each PID
visualize_plan_graph -i plans.json -o plans.png --group-by-pid

# Resolve table OIDs by connecting to the database
visualize_plan_graph -i plans.json -o plans.png --db-url postgres://user:pass@host/db
```

## 📄 Example Usage

### Preparing the Environment

To see the tool in action, you can set up a simple PostgreSQL environment with some test data:

```sql
CREATE TABLE test1(id INTEGER PRIMARY KEY);
CREATE TABLE test2(id INTEGER PRIMARY KEY);

INSERT INTO test1 SELECT generate_series(1, 1000);
INSERT INTO test2 SELECT generate_series(1, 1000);

ANALYZE;
```

### SELECT

In the first example, we will run a simple `SELECT` query and trace the planning process to see all the alternatives considered by the optimizer. To capture the planning of this query, we can run the following command:

```
$ sudo pg_plan_alternatives -x /home/jan/postgresql-sandbox/bin/REL_17_1_DEBUG/bin/postgres -n $(pg_config --includedir-server)/nodes/nodetags.h
```

In another terminal, we execute the query:

```sql
SELECT * FROM test1;
```

The output from `pg_plan_alternatives` will show all the paths that were considered for this query, including sequential scans, index scans, and bitmap heap scans, along with their estimated costs. The chosen plan will be highlighted in the output with a `[CHOSEN]` tag.

```
================================================================================
PostgreSQL Plan Alternatives Tracer
Binary: /home/jan/postgresql-sandbox/bin/REL_17_1_DEBUG/bin/postgres
Tracing all PostgreSQL processes
================================================================================

Received event: PID=3917080, Type=ADD_PATH, PathType=T_SeqScan
[20:14:54.116] [PID 3917080] ADD_PATH: T_SeqScan (startup=0.00, total=15.00, rows=1000, parent_rti=1, parent_oid=26144)
Received event: PID=3917080, Type=ADD_PATH, PathType=T_IndexOnlyScan
[20:14:54.118] [PID 3917080] ADD_PATH: T_IndexOnlyScan (startup=0.28, total=43.27, rows=1000, parent_rti=1, parent_oid=26144)
Received event: PID=3917080, Type=ADD_PATH, PathType=T_BitmapHeapScan
[20:14:54.118] [PID 3917080] ADD_PATH: T_BitmapHeapScan (startup=25.52, total=40.52, rows=1000, parent_rti=1, parent_oid=26144)
Received event: PID=3917080, Type=ADD_PATH, PathType=T_SeqScan
[20:14:54.118] [PID 3917080] ADD_PATH: T_SeqScan (startup=0.00, total=15.00, rows=1000, parent_oid=26144)
Received event: PID=3917080, Type=CREATE_PLAN, PathType=T_SeqScan
[20:14:54.118] [PID 3917080] CREATE_PLAN: T_SeqScan (startup=0.00, total=15.00) [CHOSEN]
```

When we run `EXPLAIN (VERBOSE, ANALYZE)` on the same query, we can see that the chosen plan was a sequential scan, which matches the output from our tracer. Also the costs and estimated rows align with what was reported in the trace output.

```
jan2=# EXPLAIN (VERBOSE, ANALYZE) SELECT * FROM test1;
                                                 QUERY PLAN
-------------------------------------------------------------------------------------------------------------
 Seq Scan on public.test1  (cost=0.00..15.00 rows=1000 width=4) (actual time=0.119..0.291 rows=1000 loops=1)
   Output: id
 Planning Time: 0.855 ms
 Execution Time: 0.437 ms
(4 rows)
```

To visualize the alternatives, we can save the trace output to a JSON file and then create an SVG graph:

```
$ sudo pg_plan_alternatives -x /home/jan/postgresql-sandbox/bin/REL_17_1_DEBUG/bin/postgres -n $(pg_config --includedir-server)/nodes/nodetags.h -j -o examples/select.json
```

From this JSON file, we can generate a graph visualization. The `--db-url` option allows the tool to connect to the database and resolve OIDs to human-readable table names, which makes the graph easier to understand.

```
$ visualize_plan_graph -i examples/select.json -o examples/select.svg --db-url psql://localhost/jan2 -v 
```

![Select plan alternatives](https://raw.githubusercontent.com/jnidzwetzki/pg_plan_alternatives/refs/heads/main/examples/select.svg)

### SELECT with a simple WHERE clause:

In the next example, we will run a `SELECT` query with a `WHERE` clause that filters for a specific ID. 

```
SELECT * FROM test1 WHERE id = 5;
```

The trace output shows the following alternatives being considered by the optimizer:

```
Received event: PID=3917080, Type=ADD_PATH, PathType=T_SeqScan
[20:15:53.751] [PID 3917080] ADD_PATH: T_SeqScan (startup=0.00, total=17.50, rows=1, parent_rti=1, parent_oid=26144)
Received event: PID=3917080, Type=ADD_PATH, PathType=T_IndexOnlyScan
[20:15:53.751] [PID 3917080] ADD_PATH: T_IndexOnlyScan (startup=0.28, total=8.29, rows=1, parent_rti=1, parent_oid=26144)
Received event: PID=3917080, Type=ADD_PATH, PathType=T_BitmapHeapScan
[20:15:53.751] [PID 3917080] ADD_PATH: T_BitmapHeapScan (startup=4.28, total=8.30, rows=1, parent_rti=1, parent_oid=26144)
Received event: PID=3917080, Type=ADD_PATH, PathType=T_IndexOnlyScan
[20:15:53.751] [PID 3917080] ADD_PATH: T_IndexOnlyScan (startup=0.28, total=8.29, rows=1, parent_oid=26144)
Received event: PID=3917080, Type=CREATE_PLAN, PathType=T_IndexOnlyScan
[20:15:53.751] [PID 3917080] CREATE_PLAN: T_IndexOnlyScan (startup=0.28, total=8.29) [CHOSEN]
```

This time the optimizer has chosen the `Index Only Scan` plan, which has the lowest estimated cost. When we run `EXPLAIN (VERBOSE, ANALYZE)` on this query, we can confirm that the chosen plan matches what was reported in the trace output.

```
jan2=# EXPLAIN (VERBOSE, ANALYZE) SELECT * FROM test1 WHERE id = 5;
                                                          QUERY PLAN
------------------------------------------------------------------------------------------------------------------------------
 Index Only Scan using test1_pkey on public.test1  (cost=0.28..8.29 rows=1 width=4) (actual time=0.153..0.160 rows=1 loops=1)
   Output: id
   Index Cond: (test1.id = 5)
   Heap Fetches: 1
 Planning Time: 1.166 ms
 Execution Time: 0.284 ms
(6 rows)
```

The visualization of the alternatives for this query looks like this:

![Select plan alternatives](https://raw.githubusercontent.com/jnidzwetzki/pg_plan_alternatives/refs/heads/main/examples/select_where.svg)

### JOIN

To give a more complex example, we can run a `JOIN` query that combines data from both `test1` and `test2`:

```sql
SELECT * FROM test1 LEFT JOIN test2 ON (test1.id = test2.id);
```

Now far more alternatives are considered by the optimizer, including different join strategies (merge join, hash join, nested loop) and different scan methods for each table. 

```
Received event: PID=3917080, Type=ADD_PATH, PathType=T_SeqScan
[20:22:42.381] [PID 3917080] ADD_PATH: T_SeqScan (startup=0.00, total=15.00, rows=1000, parent_rti=1, parent_oid=26144)
Received event: PID=3917080, Type=ADD_PATH, PathType=T_IndexOnlyScan
[20:22:42.381] [PID 3917080] ADD_PATH: T_IndexOnlyScan (startup=0.28, total=43.27, rows=1000, parent_rti=1, parent_oid=26144)
Received event: PID=3917080, Type=ADD_PATH, PathType=T_SeqScan
[20:22:42.381] [PID 3917080] ADD_PATH: T_SeqScan (startup=0.00, total=15.00, rows=1000, parent_rti=2, parent_oid=26149)
Received event: PID=3917080, Type=ADD_PATH, PathType=T_IndexOnlyScan
[20:22:42.382] [PID 3917080] ADD_PATH: T_IndexOnlyScan (startup=0.28, total=43.27, rows=1000, parent_rti=2, parent_oid=26149)
Received event: PID=3917080, Type=ADD_PATH, PathType=T_IndexOnlyScan
[20:22:42.383] [PID 3917080] ADD_PATH: T_IndexOnlyScan (startup=0.28, total=0.33, rows=1, parent_rti=2, parent_oid=26149)
Received event: PID=3917080, Type=ADD_PATH, PathType=T_BitmapHeapScan
[20:22:42.383] [PID 3917080] ADD_PATH: T_BitmapHeapScan (startup=0.30, total=4.32, rows=1, parent_rti=2, parent_oid=26149)
Received event: PID=3917080, Type=ADD_PATH, PathType=T_MergeJoin
[20:22:42.385] [PID 3917080] ADD_PATH: T_MergeJoin (startup=129.66, total=149.66, rows=1000, join=JOIN_LEFT, outer_rti=1, outer_oid=26144, inner_rti=2, inner_oid=26149)
Received event: PID=3917080, Type=ADD_PATH, PathType=T_NestLoop
[20:22:42.385] [PID 3917080] ADD_PATH: T_NestLoop (startup=0.00, total=27487.55, rows=1000, join=JOIN_LEFT, outer_rti=1, outer_oid=26144, inner_rti=2, inner_oid=26149)
Received event: PID=3917080, Type=ADD_PATH, PathType=T_NestLoop
[20:22:42.385] [PID 3917080] ADD_PATH: T_NestLoop (startup=0.00, total=15017.53, rows=1000, join=JOIN_LEFT, outer_rti=1, outer_oid=26144, inner_rti=2, inner_oid=26149)
Received event: PID=3917080, Type=ADD_PATH, PathType=T_NestLoop
[20:22:42.385] [PID 3917080] ADD_PATH: T_NestLoop (startup=0.28, total=27515.83, rows=1000, join=JOIN_LEFT, outer_rti=1, outer_oid=26144, inner_rti=2, inner_oid=26149)
Received event: PID=3917080, Type=ADD_PATH, PathType=T_NestLoop
[20:22:42.385] [PID 3917080] ADD_PATH: T_NestLoop (startup=0.28, total=15045.80, rows=1000, join=JOIN_LEFT, outer_rti=1, outer_oid=26144, inner_rti=2, inner_oid=26149)
Received event: PID=3917080, Type=ADD_PATH, PathType=T_MergeJoin
[20:22:42.386] [PID 3917080] ADD_PATH: T_MergeJoin (startup=65.10, total=125.60, rows=1000, join=JOIN_LEFT, outer_rti=1, outer_oid=26144, inner_rti=2, inner_oid=26149)
Received event: PID=3917080, Type=ADD_PATH, PathType=T_MergeJoin
[20:22:42.386] [PID 3917080] ADD_PATH: T_MergeJoin (startup=0.55, total=101.55, rows=1000, join=JOIN_LEFT, outer_rti=1, outer_oid=26144, inner_rti=2, inner_oid=26149)
Received event: PID=3917080, Type=ADD_PATH, PathType=T_HashJoin
[20:22:42.386] [PID 3917080] ADD_PATH: T_HashJoin (startup=27.50, total=45.14, rows=1000, join=JOIN_LEFT, outer_rti=1, outer_oid=26144, inner_rti=2, inner_oid=26149)
Received event: PID=3917080, Type=ADD_PATH, PathType=T_HashJoin
[20:22:42.387] [PID 3917080] ADD_PATH: T_HashJoin (startup=27.50, total=45.14, rows=1000, join=JOIN_RIGHT, outer_rti=2, outer_oid=26149, inner_rti=1, inner_oid=26144)
Received event: PID=3917080, Type=ADD_PATH, PathType=T_HashJoin
[20:22:42.387] [PID 3917080] ADD_PATH: T_HashJoin (startup=27.50, total=45.14, rows=1000, join=JOIN_LEFT, outer_rti=1, outer_oid=26144, inner_rti=2, inner_oid=26149)
Received event: PID=3917080, Type=CREATE_PLAN, PathType=T_HashJoin
[20:22:42.387] [PID 3917080] CREATE_PLAN: T_HashJoin (startup=27.50, total=45.14) [CHOSEN]
Received event: PID=3917080, Type=CREATE_PLAN, PathType=T_SeqScan
[20:22:42.387] [PID 3917080] CREATE_PLAN: T_SeqScan (startup=0.00, total=15.00) [CHOSEN]
Received event: PID=3917080, Type=CREATE_PLAN, PathType=T_SeqScan
[20:22:42.387] [PID 3917080] CREATE_PLAN: T_SeqScan (startup=0.00, total=15.00) [CHOSEN]
```

According to the trace output, the optimizer has chosen a `Hash Join` strategy for the join operation, and sequential scans for both tables. When we run `EXPLAIN (VERBOSE, ANALYZE)` on this query, we can confirm that the chosen plan matches what was reported in the trace output.

```
jan2=# EXPLAIN (VERBOSE, ANALYZE) SELECT * FROM test1 LEFT JOIN test2 ON (test1.id = test2.id);
                                                       QUERY PLAN
-------------------------------------------------------------------------------------------------------------------------
 Hash Left Join  (cost=27.50..45.14 rows=1000 width=8) (actual time=0.625..1.422 rows=1000 loops=1)
   Output: test1.id, test2.id
   Inner Unique: true
   Hash Cond: (test1.id = test2.id)
   ->  Seq Scan on public.test1  (cost=0.00..15.00 rows=1000 width=4) (actual time=0.038..0.220 rows=1000 loops=1)
         Output: test1.id
   ->  Hash  (cost=15.00..15.00 rows=1000 width=4) (actual time=0.571..0.572 rows=1000 loops=1)
         Output: test2.id
         Buckets: 1024  Batches: 1  Memory Usage: 44kB
         ->  Seq Scan on public.test2  (cost=0.00..15.00 rows=1000 width=4) (actual time=0.019..0.191 rows=1000 loops=1)
               Output: test2.id
 Planning Time: 3.436 ms
 Execution Time: 1.551 ms
(13 rows)
```

The visualization of the alternatives for this query looks like this:

![Select plan alternatives](https://raw.githubusercontent.com/jnidzwetzki/pg_plan_alternatives/refs/heads/main/examples/join.svg)


### JOIN with a WHERE clause

As the last example, we run a `JOIN` query with a `WHERE` clause that filters for a specific ID in the first table:

```sql
SELECT * FROM test1 LEFT JOIN test2 ON (test1.id = test2.id) WHERE test1.id=123;
```

The trace output shows that the optimizer has just a few join strategies to consider. 

```
Received event: PID=3917080, Type=ADD_PATH, PathType=T_SeqScan
[20:29:41.396] [PID 3917080] ADD_PATH: T_SeqScan (startup=0.00, total=17.50, rows=1, parent_rti=1, parent_oid=26144)
Received event: PID=3917080, Type=ADD_PATH, PathType=T_IndexOnlyScan
[20:29:41.396] [PID 3917080] ADD_PATH: T_IndexOnlyScan (startup=0.28, total=8.29, rows=1, parent_rti=1, parent_oid=26144)
Received event: PID=3917080, Type=ADD_PATH, PathType=T_BitmapHeapScan
[20:29:41.396] [PID 3917080] ADD_PATH: T_BitmapHeapScan (startup=4.28, total=8.30, rows=1, parent_rti=1, parent_oid=26144)
Received event: PID=3917080, Type=ADD_PATH, PathType=T_SeqScan
[20:29:41.396] [PID 3917080] ADD_PATH: T_SeqScan (startup=0.00, total=17.50, rows=1, parent_rti=2, parent_oid=26149)
Received event: PID=3917080, Type=ADD_PATH, PathType=T_IndexOnlyScan
[20:29:41.396] [PID 3917080] ADD_PATH: T_IndexOnlyScan (startup=0.28, total=8.29, rows=1, parent_rti=2, parent_oid=26149)
Received event: PID=3917080, Type=ADD_PATH, PathType=T_BitmapHeapScan
[20:29:41.396] [PID 3917080] ADD_PATH: T_BitmapHeapScan (startup=4.28, total=8.30, rows=1, parent_rti=2, parent_oid=26149)
Received event: PID=3917080, Type=ADD_PATH, PathType=T_NestLoop
[20:29:41.397] [PID 3917080] ADD_PATH: T_NestLoop (startup=0.55, total=16.60, rows=1, join=JOIN_LEFT, outer_rti=1, outer_oid=26144, inner_rti=2, inner_oid=26149)
Received event: PID=3917080, Type=ADD_PATH, PathType=T_NestLoop
[20:29:41.397] [PID 3917080] ADD_PATH: T_NestLoop (startup=0.55, total=16.60, rows=1, join=JOIN_LEFT, outer_rti=1, outer_oid=26144, inner_rti=2, inner_oid=26149)
Received event: PID=3917080, Type=ADD_PATH, PathType=T_NestLoop
[20:29:41.397] [PID 3917080] ADD_PATH: T_NestLoop (startup=0.55, total=16.60, rows=1, join=JOIN_LEFT, outer_rti=1, outer_oid=26144, inner_rti=2, inner_oid=26149)
Received event: PID=3917080, Type=CREATE_PLAN, PathType=T_NestLoop
[20:29:41.397] [PID 3917080] CREATE_PLAN: T_NestLoop (startup=0.55, total=16.60) [CHOSEN]
Received event: PID=3917080, Type=CREATE_PLAN, PathType=T_IndexOnlyScan
[20:29:41.397] [PID 3917080] CREATE_PLAN: T_IndexOnlyScan (startup=0.28, total=8.29) [CHOSEN]
Received event: PID=3917080, Type=CREATE_PLAN, PathType=T_IndexOnlyScan
[20:29:41.397] [PID 3917080] CREATE_PLAN: T_IndexOnlyScan (startup=0.28, total=8.29) [CHOSEN]
```

This time, the optimizer has chosen a `Nested Loop Join` strategy for the join operation, and index scans for both tables. When we run `EXPLAIN (VERBOSE, ANALYZE)` on this query, we can confirm that the chosen plan matches what was reported in the trace output.


```
jan2=# EXPLAIN (VERBOSE, ANALYZE) SELECT * FROM test1 LEFT JOIN test2 ON (test1.id = test2.id) WHERE test1.id=123;
                                                             QUERY PLAN
------------------------------------------------------------------------------------------------------------------------------------
 Nested Loop Left Join  (cost=0.55..16.60 rows=1 width=8) (actual time=0.183..0.189 rows=1 loops=1)
   Output: test1.id, test2.id
   Inner Unique: true
   ->  Index Only Scan using test1_pkey on public.test1  (cost=0.28..8.29 rows=1 width=4) (actual time=0.139..0.143 rows=1 loops=1)
         Output: test1.id
         Index Cond: (test1.id = 123)
         Heap Fetches: 1
   ->  Index Only Scan using test2_pkey on public.test2  (cost=0.28..8.29 rows=1 width=4) (actual time=0.032..0.032 rows=1 loops=1)
         Output: test2.id
         Index Cond: (test2.id = 123)
         Heap Fetches: 1
 Planning Time: 1.116 ms
 Execution Time: 0.336 ms
(13 rows)
```

The visualization of the alternatives for this query looks like this:

![Select plan alternatives](https://raw.githubusercontent.com/jnidzwetzki/pg_plan_alternatives/refs/heads/main/examples/join_where.svg)

## 🎨 Visualization

The `visualize_plan_graph` tool creates visual representations of the query plans:

- **Green nodes**: Plans that were chosen for execution
- **Blue nodes**: Alternative plans that were considered but not selected
- **Node labels**: Show path type, costs, and estimated rows
- **Statistics**: Summary showing total plans considered, cheapest and most expensive plans


## 🔧 How It Works

The tool uses eBPF (Extended Berkeley Packet Filter) to instrument the `add_path()` function in PostgreSQL's query planner. This function is called every time the optimizer considers a new execution path. By capturing these calls, we can see all the alternatives that were evaluated.

The tool also instruments the `create_plan()` function to identify which path was ultimately chosen for execution.

Key instrumented functions:
- **`add_path()`**: Called when a new query plan alternative is considered
- **`create_plan()`**: Called when the chosen plan is converted to an execution plan

## ⚠️ Known Limitations

- Requires PostgreSQL to be compiled with debug symbols to be able to attach the eBPF uprobes (see below)
- Parallel plans are not currently supported (the `add_partial_path()` function is not instrumented)

## 📋 Requirements

- Linux with eBPF support (kernel 4.9+)
- Python 3.10+
- Root privileges (required for eBPF)
- PostgreSQL 14, 15, 16, 17, or 18 with debug symbols
- BCC (BPF Compiler Collection)
- graphviz (for visualization)
- psycopg2 (required for OID resolution)

### Installing Dependencies

#### Ubuntu/Debian

```bash
# Install BCC
sudo apt-get install bpfcc-tools python3-bpfcc

# Install graphviz
sudo apt-get install graphviz

# Install the tool
pip install pg_plan_alternatives
```

## PostgreSQL Build
The software is tested with PostgreSQL versions 17, and 18. In order to be able to attach the _uprobes_ to the functions, they should not to be optimized away (e.g., inlined) during the compilation of PostgreSQL. Otherwise errors like `Unable to locate function XXX` will occur.

It is recommended to compile PostgreSQL with the following CFLAGS: `CFLAGS="-ggdb -Og -g3 -fno-omit-frame-pointer"`.

## Developer Notes
## Installation

The tool can be installed system-wide or in a dedicated [virtual environment](https://docs.python.org/3/library/venv.html). To create and install the tools in such a virtual environment, the following steps must be performed. To install the tools system-wide, these steps can be skipped.

```shell
cd <installation directory>
python3 -m venv .venv
source .venv/bin/activate

# Copy the distribution Python BCC packages into this environment
cp -av /usr/lib/python3/dist-packages/bcc* $(python -c "from distutils.sysconfig import get_python_lib; print(get_python_lib())")

pip install -r requirements_dev.txt
```

## 📝 License

MIT License - see [LICENSE](LICENSE) file for details.
