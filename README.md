# PostgreSQL Plan Alternatives Tracer

[![Make a PR](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](http://makeapullrequest.com)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

An eBPF-based tool designed to show **all query plans** that are considered by PostgreSQL during query planning, not just the final chosen plan. This provides valuable insights into the PostgreSQL query optimizer's decision-making process.

## 🎯 Overview

When PostgreSQL plans a query, it considers many different execution paths and chooses the one with the lowest estimated cost. The standard `EXPLAIN` command only shows the final chosen plan. `pg_plan_alternatives` reveals all the alternative plans that were considered, along with their costs, giving you a complete picture of the optimizer's reasoning.

Key features:
- **`pg_plan_alternatives`**: eBPF-based tracer that captures all query plans considered during planning
- **`visualize_plan_graph`**: Creates interactive graph visualizations from trace output
- Supports PostgreSQL 17, and 18
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
# Trace a specific PostgreSQL backend process
sudo pg_plan_alternatives -x /usr/lib/postgresql/16/bin/postgres -p 1234 -n /path/to/nodetags.h

# Trace multiple processes
sudo pg_plan_alternatives -x /usr/lib/postgresql/16/bin/postgres -p 1234 -p 5678 -n /path/to/nodetags.h

# Trace all PostgreSQL processes using the binary
sudo pg_plan_alternatives -x /usr/lib/postgresql/16/bin/postgres -n /path/to/nodetags.h

# Output in JSON format
sudo pg_plan_alternatives -x /usr/lib/postgresql/16/bin/postgres -p 1234 -j -n /path/to/nodetags.h

# Save output to file
sudo pg_plan_alternatives -x /usr/lib/postgresql/16/bin/postgres -p 1234 -j -o plans.json -n /path/to/nodetags.h

# Verbose mode
sudo pg_plan_alternatives -x /usr/lib/postgresql/16/bin/postgres -p 1234 -v -n /path/to/nodetags.h
```

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
```

## 📄 Example Output

### CLI Output

```
================================================================================
PostgreSQL Plan Alternatives Tracer
Binary: /usr/lib/postgresql/16/bin/postgres
PIDs: 1234
================================================================================
[14:23:45.123] [PID 1234] ADD_PATH: T_SeqScan (startup=0.00, total=35.50, rows=1000)
[14:23:45.124] [PID 1234] ADD_PATH: T_IndexPath (startup=0.25, total=12.50, rows=1000)
[14:23:45.125] [PID 1234] ADD_PATH: T_BitmapHeapPath (startup=5.00, total=15.75, rows=1000)
[14:23:45.126] [PID 1234] CREATE_PLAN: T_IndexPath (startup=0.25, total=12.50) [CHOSEN]
```

### JSON Output

```json
{"timestamp": 1645012425123456789, "pid": 1234, "event_type": "ADD_PATH", "path_type": "T_SeqScan", "startup_cost": 0.0, "total_cost": 35.5, "rows": 1000, "width": 0, "parent_relid": 0, "relid": 0, "join_type": 0, "inner_relid": 0, "outer_relid": 0}
{"timestamp": 1645012425124567890, "pid": 1234, "event_type": "ADD_PATH", "path_type": "T_IndexPath", "startup_cost": 0.25, "total_cost": 12.5, "rows": 1000, "width": 0, "parent_relid": 0, "relid": 0, "join_type": 0, "inner_relid": 0, "outer_relid": 0}
{"timestamp": 1645012425125678901, "pid": 1234, "event_type": "ADD_PATH", "path_type": "T_BitmapHeapPath", "startup_cost": 5.0, "total_cost": 15.75, "rows": 1000, "width": 0, "parent_relid": 0, "relid": 0, "join_type": 0, "inner_relid": 0, "outer_relid": 0}
{"timestamp": 1645012425126789012, "pid": 1234, "event_type": "CREATE_PLAN", "path_type": "T_IndexPath", "startup_cost": 0.25, "total_cost": 12.5, "rows": 0, "width": 0, "parent_relid": 0, "relid": 0, "join_type": 0, "inner_relid": 0, "outer_relid": 0}
```

## 🔧 How It Works

The tool uses eBPF (Extended Berkeley Packet Filter) to instrument the `add_path()` function in PostgreSQL's query planner. This function is called every time the optimizer considers a new execution path. By capturing these calls, we can see all the alternatives that were evaluated.

The tool also instruments the `create_plan()` function to identify which path was ultimately chosen for execution.

Key instrumented functions:
- **`add_path()`**: Called when a new query plan alternative is considered
- **`create_plan()`**: Called when the chosen plan is converted to an execution plan

## 📋 Requirements

- Linux with eBPF support (kernel 4.9+)
- Python 3.10+
- Root privileges (required for eBPF)
- PostgreSQL 14, 15, 16, 17, or 18 with debug symbols
- BCC (BPF Compiler Collection)
- graphviz (for visualization)

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

## Developer Notes
## Installation

The PostgreSQL lock tracing tools are available as a Python package. These tools depend on the Python package for BPF. Unfortunately, this package is currently not available via `pip` (the Python package manager). Therefore, the package of the Linux distribution needs to be installed to provide this dependency. On Debian and Ubuntu, this can be done by executing the following command:

```shell
apt install python3-bpfcc
```

The tracing tools can be installed system-wide or in a dedicated [virtual environment](https://docs.python.org/3/library/venv.html). To create and install the tools in such a virtual environment, the following steps must be performed. To install the tools system-wide, these steps can be skipped.

```shell
cd <installation directory>
python3 -m venv .venv
source .venv/bin/activate

# Copy the distribution Python BCC packages into this environment
cp -av /usr/lib/python3/dist-packages/bcc* $(python -c "from distutils.sysconfig import get_python_lib; print(get_python_lib())")

pip install -r requirements_dev.txt
```

## 🎨 Visualization

The `visualize_plan_graph` tool creates visual representations of the query plans:

- **Green nodes**: Plans that were chosen for execution
- **Blue nodes**: Alternative plans that were considered but not selected
- **Node labels**: Show path type, costs, and estimated rows
- **Statistics**: Summary showing total plans considered, cheapest and most expensive plans

## 📝 License

MIT License - see [LICENSE](LICENSE) file for details.
