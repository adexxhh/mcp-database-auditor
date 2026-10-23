import json
from decimal import Decimal
import pytest
from security.guardrail import SQLGuardrail, UnsafeQueryException
from core.profiler import AuditProfiler
import server

@pytest.mark.parametrize("sql", [
 "WITH x AS (DELETE FROM users RETURNING *) SELECT * FROM x",
 "SELECT * INTO backup FROM users",
 "SELECT * FROM users FOR UPDATE",
 "SELECT pg_sleep(30)",
 "SELECT * FROM users LIMIT -1",
 "SELECT * FROM users LIMIT ALL",
 "SELECT * FROM users LIMIT (SELECT 100000)",
])
def test_side_effects_and_unbounded_limits_rejected(sql):
    with pytest.raises(UnsafeQueryException):
        SQLGuardrail().validate(sql)

def test_json_and_decimal_profile():
    report = AuditProfiler().profile([{"payload":{"x":1},"amount":Decimal("2.5")},
                                     {"payload":{"x":1},"amount":Decimal("3.5")}], "SELECT")
    assert report.column_profiles[0].unique_count == 1
    assert report.column_profiles[1].mean_val == 3

@pytest.mark.asyncio
async def test_audit_fingerprint_and_snapshot(monkeypatch, tmp_path):
    path=tmp_path/"events.jsonl"
    monkeypatch.setenv("AUDIT_LOG_PATH",str(path))
    await server.execute_safe_query("SELECT * FROM users WHERE id = 1")
    await server.execute_safe_query("SELECT * FROM users WHERE id = 2")
    rows=[json.loads(line) for line in path.read_text().splitlines()]
    assert rows[0]["fingerprint"] == rows[1]["fingerprint"]
    assert "sql" not in rows[0]
    assert json.loads(await server.schema_changes())["baseline_created"]
    assert json.loads(await server.schema_changes()) == {"added":[],"removed":[],"changed":[]}

@pytest.mark.asyncio
async def test_query_plan_uses_real_database():
    scan = json.loads(await server.analyze_query_plan("SELECT name FROM users"))
    assert scan["full_scan_candidates"] and scan["plan"]
    lookup = json.loads(await server.analyze_query_plan("SELECT name FROM users WHERE id = 1"))
    assert not lookup["full_scan_candidates"]
