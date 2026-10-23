# MCP Database Auditor

Inspect database schemas, profile tables and review SQL query plans through the Model Context Protocol.

The auditor gives an MCP client structured access to SQLite and PostgreSQL metadata and read-only queries. SQL policy checks, database permissions and execution deadlines help keep exploratory database work controlled.

## Features

- **Schema exploration:** tables, columns, keys, indexes and relationships exposed as MCP resources.
- **Read-only queries:** SQLGlot AST validation, function policies and bounded result limits.
- **Table profiling:** sampled column statistics, including JSON and decimal values.
- **Query-plan inspection:** EXPLAIN output with scan and indexing observations.
- **Audit records:** JSONL events with execution outcomes and normalized query fingerprints.
- **Schema comparison:** changes between successive in-process snapshots.

## Architecture

~~~mermaid
flowchart LR
  Client[MCP client] --> Tools[FastMCP tools and resources]
  Tools --> Policy[SQL AST validation]
  Policy --> Database[Read-only SQLite or PostgreSQL]
  Database --> Results[Rows, schema and query plans]
  Results --> Output[Profiles, audit events and responses]
~~~

| MCP tool | Purpose |
|---|---|
| execute_safe_query | Validate and execute a read-only query |
| profile_table | Summarize a sample of table data |
| get_database_health | Report connection and database information |
| analyze_query_plan | Inspect the database query plan |
| schema_changes | Compare the current schema with the previous snapshot |

Schema resources: schema://current and schema://table/{table_name}.

## Quick start

~~~sh
python -m venv .venv
# Activate the environment, then install:
pip install -e ".[dev]"
python scripts/seed_demo_db.py
python server.py
~~~

In another terminal with the environment activated:

~~~sh
python client_test.py
~~~

The default transport is stdio. DATABASE_URL selects a database connection; the default configuration initializes a local SQLite demo. AUDIT_LOG_PATH selects the JSONL audit destination.

For local SSE:

~~~sh
python server.py --transport sse --host 127.0.0.1 --port 8000
~~~

Use least-privilege database roles. A hosted SSE deployment also needs an authentication layer.

## PostgreSQL

The Compose configuration separates the database owner from a SELECT-only reader:

~~~sh
docker compose up --build
~~~

Use the disposable reader URL from docker-compose.yml for TEST_POSTGRES_URL when running the PostgreSQL integration test:

~~~sh
python -m pytest tests/test_postgres_integration.py -q
~~~

## Validation and performance

~~~sh
python -m pytest -q
python benchmark.py --repeats 30 --output benchmark-results.json
~~~

The local suite passes 58 tests. Linux CI also passes the PostgreSQL integration job and the SQLite/MCP checks.

| Operation | Median | p95 |
|---|---:|---:|
| Schema reflection | 14.80 ms | 15.80 ms |
| SQL policy validation | 0.445 ms | 0.591 ms |

Measurements use 30 runs on a seeded five-table local SQLite database. [Benchmark samples](docs/evidence/sqlite-benchmark.json) ? [CI results](https://github.com/adexxhh/mcp-database-auditor/actions/runs/39961281678)

Profiles summarize the first 100 returned rows. Schema comparison state lasts for the server process, and query-plan observations should be interpreted alongside the database workload.

## Demo

![Database auditor terminal walkthrough](assets/demo.gif)

[PNG](assets/demo.png) ? [Command transcript](assets/demo-transcript.json)

Regenerate the terminal walkthrough with requirements-demo.txt and python scripts/render_demo.py.

## Development

[Engineering guide](OWNERSHIP.md) ? [CPU service-check notebook](scripts/colab_service_checks.ipynb) ? [Continuation notes](HANDOFF.md)
