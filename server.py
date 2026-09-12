"""
Official FastMCP Server for Database Auditor MCP.
Exposes MCP tools, resources, and prompts for database auditing, safety guardrails,
schema reflection, and analytical profiling.
"""

import argparse
import asyncio
import os
import sys
import time
from typing import Any, Dict, List, Optional

from mcp.server.fastmcp import FastMCP, Context
from security.guardrail import (
    SQLGuardrail,
    UnsafeQueryException,
    DisallowedCommandException,
    ASTParsingException,
)
from core.database import (
    DatabaseEngine,
    DatabaseEngineException,
    QueryTimeoutException,
    ReadOnlyViolationException,
    RelationshipGraph,
    TableSchema,
)
from core.profiler import AuditProfiler, AuditReport
from scripts.seed_demo_db import seed_demo_database, DEFAULT_DB_FILE


# Initialize FastMCP Server
mcp = FastMCP("Database Auditor MCP")

# Global instances (initialized on demand or startup)
_db_engine: Optional[DatabaseEngine] = None
_guardrail: SQLGuardrail = SQLGuardrail(default_limit=100, max_limit=1000)
_profiler: AuditProfiler = AuditProfiler()


def get_db_url() -> str:
    """Returns database connection URL from environment or default demo database."""
    env_url = os.getenv("DATABASE_URL")
    if env_url:
        return env_url
    
    db_file = os.path.abspath(DEFAULT_DB_FILE)
    if not os.path.exists(db_file):
        asyncio.run(seed_demo_database(f"sqlite+aiosqlite:///{db_file}"))
    
    return f"sqlite+aiosqlite:///{db_file}"


def get_engine() -> DatabaseEngine:
    """Returns or lazily creates the DatabaseEngine instance."""
    global _db_engine
    if _db_engine is None:
        db_url = get_db_url()
        _db_engine = DatabaseEngine(db_url=db_url, statement_timeout=5.0, read_only=True)
    return _db_engine


# ============================================================================
# MCP TOOLS
# ============================================================================

@mcp.tool()
async def execute_safe_query(sql: str) -> str:
    """
    Validates a SQL query using the deterministic SQLGuardrail (enforcing read-only SELECT,
    comment stripping, and resource LIMITs) and executes it safely in a sandboxed read-only database session.

    Args:
        sql: Candidate SQL query string to evaluate and execute.

    Returns:
        Markdown table string of query results or an formatted error message.
    """
    try:
        # 1. AST Safety & Guardrail Validation
        validated_sql = _guardrail.validate_and_transform(sql)

        # 2. Measure & Execute Query in Read-Only Sandbox
        engine = get_engine()
        start_time = time.perf_counter()
        rows = await engine.execute_query(validated_sql)
        duration_ms = (time.perf_counter() - start_time) * 1000.0

        if not rows:
            return f"### Query Result\n*Query executed successfully in {duration_ms:.2f} ms but returned 0 rows.*\n\n**Validated Query**:\n```sql\n{validated_sql}\n```"

        # Format as Markdown Table
        headers = list(rows[0].keys())
        md_lines = []
        md_lines.append(f"### Query Execution Results ({len(rows)} rows, {duration_ms:.2f} ms)")
        md_lines.append(f"**Executed SQL**: `{validated_sql}`\n")
        
        md_lines.append("| " + " | ".join(headers) + " |")
        md_lines.append("| " + " | ".join(["---"] * len(headers)) + " |")

        for row in rows:
            row_vals = [str(row.get(h, "")).replace("\n", " ") for h in headers]
            md_lines.append("| " + " | ".join(row_vals) + " |")

        return "\n".join(md_lines)

    except DisallowedCommandException as exc:
        return f"❌ **SECURITY GUARDRAIL REJECTION [DisallowedCommandException]**:\n> {exc}\n\n*Only read-only `SELECT` queries are permitted.*"
    except ASTParsingException as exc:
        return f"❌ **SQL PARSING ERROR [ASTParsingException]**:\n> {exc}"
    except UnsafeQueryException as exc:
        return f"❌ **UNSAFE QUERY REJECTION [UnsafeQueryException]**:\n> {exc}"
    except QueryTimeoutException as exc:
        return f"⏱️ **STATEMENT TIMEOUT [QueryTimeoutException]**:\n> {exc}"
    except ReadOnlyViolationException as exc:
        return f"🔒 **READ-ONLY ISOLATION VIOLATION [ReadOnlyViolationException]**:\n> {exc}"
    except DatabaseEngineException as exc:
        return f"⚠️ **DATABASE ENGINE ERROR [DatabaseEngineException]**:\n> {exc}"
    except Exception as exc:
        return f"💥 **INTERNAL PROTOCOL ERROR**: {type(exc).__name__}: {exc}"


@mcp.tool()
async def profile_table(table_name: str) -> str:
    """
    Runs the automated AuditProfiler across a target table to generate a comprehensive
    statistical health audit, null rates, cardinality ratios, outliers, and distribution charts.

    Args:
        table_name: Name of the database table to audit.

    Returns:
        GitHub-Flavored Markdown report summarizing table health and statistics.
    """
    try:
        clean_table = table_name.strip().strip("`\"'")
        if not clean_table.isidentifier():
            return f"❌ **INVALID TABLE NAME**: Table name '{table_name}' contains invalid characters."

        sql = f"SELECT * FROM {clean_table}"
        validated_sql = _guardrail.validate_and_transform(sql)

        engine = get_engine()
        start_time = time.perf_counter()
        rows = await engine.execute_query(validated_sql)
        duration_ms = (time.perf_counter() - start_time) * 1000.0

        report: AuditReport = _profiler.profile(
            rows=rows,
            query=validated_sql,
            execution_time_ms=duration_ms,
        )

        return _profiler.to_markdown(report)

    except Exception as exc:
        return f"❌ **PROFILER ERROR**: Failed to profile table '{table_name}': {exc}"


@mcp.tool()
async def get_database_health() -> str:
    """
    Inspects live database schema and returns a global health summary report detailing table sizes,
    unindexed foreign key columns, key null anomalies, and relationship counts.

    Returns:
        Markdown database health summary report.
    """
    try:
        engine = get_engine()
        graph: RelationshipGraph = await engine.inspect_schema()

        table_count = len(graph.tables)
        fk_count = len(graph.foreign_key_edges)

        unindexed_fks: List[str] = []
        for tname, tbl in graph.tables.items():
            indexed_cols = set()
            for idx in tbl.indexes:
                indexed_cols.update(idx.column_names)

            for fk in tbl.foreign_keys:
                for c in fk.constrained_columns:
                    if c not in indexed_cols and c not in tbl.primary_key:
                        unindexed_fks.append(f"`{tname}.{c}` -> `{fk.referred_table}.{fk.referred_columns}`")

        md: List[str] = []
        md.append("# 🏥 Database Health & Audit Summary")
        md.append(f"- **Total Reflected Tables**: `{table_count}`")
        md.append(f"- **Total Foreign Key Relationships**: `{fk_count}`")
        md.append("")

        if unindexed_fks:
            md.append("## ⚠️ Unindexed Foreign Key Columns")
            md.append("> Foreign key columns without supporting indexes can cause severe join performance degradation:")
            for ufk in unindexed_fks:
                md.append(f"- {ufk}")
            md.append("")
        else:
            md.append("> [!NOTE]\n> All foreign key columns have supporting indexes.")
            md.append("")

        md.append("## Reflected Table Overview")
        md.append("| Table Name | Columns | Primary Key | Foreign Keys | Indexes |")
        md.append("| :--- | :--- | :--- | :--- | :--- |")

        for tname, tbl in graph.tables.items():
            pk_str = ", ".join(tbl.primary_key) if tbl.primary_key else "None"
            fk_str = str(len(tbl.foreign_keys))
            idx_str = str(len(tbl.indexes))
            md.append(f"| **{tname}** | {len(tbl.columns)} | `{pk_str}` | {fk_str} | {idx_str} |")

        return "\n".join(md)

    except Exception as exc:
        return f"❌ **HEALTH CHECK ERROR**: {exc}"


# ============================================================================
# MCP RESOURCES
# ============================================================================

@mcp.resource("schema://current")
async def get_current_schema() -> str:
    """
    Read-only JSON resource exposing the full live database relationship graph.
    """
    engine = get_engine()
    graph: RelationshipGraph = await engine.inspect_schema()
    return graph.model_dump_json(indent=2)


@mcp.resource("schema://table/{table_name}")
async def get_table_schema(table_name: str) -> str:
    """
    Read-only JSON resource returning DDL and schema context for an individual table.
    """
    clean_table = table_name.strip().strip("`\"'")
    engine = get_engine()
    graph: RelationshipGraph = await engine.inspect_schema()

    if clean_table not in graph.tables:
        return f"{{\"error\": \"Table '{clean_table}' not found in database schema.\"}}"

    table_schema: TableSchema = graph.tables[clean_table]
    return table_schema.model_dump_json(indent=2)


# ============================================================================
# MCP PROMPTS
# ============================================================================

@mcp.prompt("audit_database_anomalies")
def audit_database_anomalies_prompt() -> str:
    """
    Reusable agent prompt directing the LLM to inspect database tables, audit foreign key
    integrity, detect unindexed joins, and identify anomalous transaction spikes.
    """
    return (
        "You are an expert Database Security & Performance Auditor.\n\n"
        "Your mission is to perform a thorough audit of the database schema and query workloads:\n"
        "1. First, call `get_database_health()` to inspect all tables, foreign keys, and unindexed join columns.\n"
        "2. Read the `schema://current` resource to understand table relationships.\n"
        "3. Run `profile_table()` across key tables (e.g. `transactions`, `invoices`, `users`) to detect null key violations or numerical outliers.\n"
        "4. Use `execute_safe_query()` to investigate any suspicious financial records (e.g. anomalous charges, negative amounts, or unverified wire routes).\n"
        "5. Synthesize your findings into a comprehensive, professional Markdown audit report."
    )


# ============================================================================
# CLI & TRANSPORT ENTRYPOINT
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description="Database Auditor MCP Server")
    parser.add_argument("--db-url", type=str, help="Database connection URL")
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse"],
        default="stdio",
        help="Transport type (default: stdio)",
    )
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Host IP for SSE transport")
    parser.add_argument("--port", type=int, default=8000, help="Port number for SSE transport")

    args = parser.parse_args()

    if args.db_url:
        os.environ["DATABASE_URL"] = args.db_url

    if args.transport == "sse":
        print(f"Starting Database Auditor MCP server on SSE transport (http://{args.host}:{args.port})...")
        mcp.settings.host = args.host
        mcp.settings.port = args.port
        mcp.run(transport="sse")
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
