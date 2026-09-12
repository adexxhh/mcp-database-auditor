import json
import pytest
import pytest_asyncio
from server import (
    execute_safe_query,
    profile_table,
    get_database_health,
    get_current_schema,
    get_table_schema,
    audit_database_anomalies_prompt,
)


@pytest.mark.asyncio
async def test_mcp_execute_safe_query_valid():
    """Test execute_safe_query tool with a valid read-only SELECT statement."""
    res = await execute_safe_query("SELECT id, name, domain FROM tenants")
    assert "Query Execution Results" in res
    assert "Acme Corp" in res
    assert "| id | name | domain |" in res


@pytest.mark.asyncio
async def test_mcp_execute_safe_query_rejection():
    """Test execute_safe_query tool rejects destructive commands with security alert."""
    res = await execute_safe_query("DROP TABLE users")
    assert "SECURITY GUARDRAIL REJECTION" in res
    assert "DisallowedCommandException" in res


@pytest.mark.asyncio
async def test_mcp_execute_safe_query_syntax_error():
    """Test execute_safe_query tool handles syntax errors gracefully."""
    res = await execute_safe_query("SELECT FROM WHERE ???")
    assert "SQL PARSING ERROR" in res
    assert "ASTParsingException" in res


@pytest.mark.asyncio
async def test_mcp_profile_table():
    """Test profile_table tool outputs complete Markdown profile report."""
    res = await profile_table("transactions")
    assert "# Database Audit & Data Profiling Report" in res
    assert "Column Profiles & Statistical Summary" in res
    assert "amount" in res


@pytest.mark.asyncio
async def test_mcp_profile_table_invalid_name():
    """Test profile_table tool validates input table names."""
    res = await profile_table("users; DROP TABLE users")
    assert "INVALID TABLE NAME" in res


@pytest.mark.asyncio
async def test_mcp_get_database_health():
    """Test get_database_health tool returns overall health summary."""
    res = await get_database_health()
    assert "# 🏥 Database Health & Audit Summary" in res
    assert "Total Reflected Tables" in res
    assert "users" in res


@pytest.mark.asyncio
async def test_mcp_resource_current_schema():
    """Test schema://current resource returns live JSON relationship graph."""
    res = await get_current_schema()
    parsed = json.loads(res)
    assert "tables" in parsed
    assert "tenants" in parsed["tables"]
    assert "users" in parsed["tables"]


@pytest.mark.asyncio
async def test_mcp_resource_table_schema():
    """Test schema://table/{table_name} resource returns DDL/schema context for table."""
    res = await get_table_schema("users")
    parsed = json.loads(res)
    assert parsed["name"] == "users"
    col_names = [c["name"] for c in parsed["columns"]]
    assert "email" in col_names

    # Test non-existent table
    err_res = await get_table_schema("non_existent_tbl")
    assert "error" in json.loads(err_res)


def test_mcp_prompt_audit_anomalies():
    """Test audit_database_anomalies prompt returns non-empty agent instructions."""
    prompt_text = audit_database_anomalies_prompt()
    assert "Database Security & Performance Auditor" in prompt_text
    assert "get_database_health()" in prompt_text
    assert "profile_table()" in prompt_text
