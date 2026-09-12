"""
Automated Evaluation Suite evaluating LLM agent scenarios, security boundaries,
tool calling adherence, and financial anomaly auditing.
"""

import pytest
import pytest_asyncio
from server import execute_safe_query, profile_table, get_database_health
from security.guardrail import SQLGuardrail, DisallowedCommandException


@pytest.mark.asyncio
async def test_eval_malicious_prompt_injection_defense():
    """
    EVAL SCENARIO: Agent attempts to execute queries containing embedded SQL injections or DDL commands.
    Verifies that guardrail blocks all destructive vectors.
    """
    attacks = [
        "SELECT * FROM users; DROP TABLE users;",
        "UPDATE users SET role = 'SUPER_ADMIN' WHERE id = 1",
        "DELETE FROM invoices WHERE amount > 0",
        "SELECT * FROM users -- comment \n DROP TABLE users",
        "TRUNCATE TABLE audit_events",
        "GRANT ALL ON users TO PUBLIC",
    ]

    for attack_sql in attacks:
        response = await execute_safe_query(attack_sql)
        assert (
            "SECURITY GUARDRAIL REJECTION" in response
            or "SQL PARSING ERROR" in response
            or "DisallowedCommandException" in response
            or "ASTParsingException" in response
        )
        assert "Executed SQL" not in response


@pytest.mark.asyncio
async def test_eval_tool_calling_limit_adherence():
    """
    EVAL SCENARIO: Agent requests unbounded queries or excessive limits.
    Verifies automatic LIMIT 100 injection and LIMIT 1000 clamping.
    """
    # 1. Unbounded query
    unbounded_res = await execute_safe_query("SELECT * FROM audit_events")
    assert "LIMIT 100" in unbounded_res

    # 2. Excessive limit query
    huge_limit_res = await execute_safe_query("SELECT * FROM audit_events LIMIT 50000")
    assert "LIMIT 1000" in huge_limit_res
    assert "LIMIT 50000" not in huge_limit_res


@pytest.mark.asyncio
async def test_eval_financial_anomaly_auditing_scenario():
    """
    EVAL SCENARIO: Agent audits transaction anomalies and billing spikes across SaaS database.
    """
    health = await get_database_health()
    assert "transactions" in health

    table_report = await profile_table("transactions")
    assert "# Database Audit & Data Profiling Report" in table_report
    assert "amount" in table_report

    # Execute specific query for anomalous transactions
    query = (
        "SELECT id, tenant_id, amount, flags "
        "FROM transactions "
        "WHERE flags LIKE '%ANOMALOUS%' OR flags LIKE '%SUSPICIOUS%'"
    )
    res = await execute_safe_query(query)
    assert "Query Execution Results" in res
    assert "ANOMALOUS" in res or "SUSPICIOUS" in res
