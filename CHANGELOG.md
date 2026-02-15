# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-02-15

### Added
- Initial release of pg_plan_alternatives
- eBPF-based tracer for PostgreSQL query plan alternatives (`pg_plan_alternatives`)
- Graph visualization tool (`visualize_plan_graph`)
- Support for PostgreSQL 14, 15, 16, 17, and 18
- JSON output format for trace data
- Interactive HTML visualization with SVG graphs
- Helper utilities for BPF operations and path type handling
- Comprehensive documentation (README, INSTALL, examples)
- Basic test suite
- Example SQL queries and usage scenarios

### Features
- Traces `add_path()` function to capture all considered query plans
- Traces `create_plan()` function to identify chosen plan
- Shows startup cost, total cost, and row estimates for each plan
- Supports filtering by PID
- Supports grouping visualizations by PID
- Multiple output formats (PNG, SVG, PDF, HTML)

[0.1.0]: https://github.com/jnidzwetzki/pg_plan_alternatives/releases/tag/v0.1.0
