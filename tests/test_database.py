import asyncio
import os
import pytest
import pytest_asyncio
from core.database import (
    DatabaseEngine,
    DatabaseEngineException,
    QueryTimeoutException,
    ReadOnlyViolationException,
    RelationshipGraph,
    TableSchema,
)
from scripts.seed_demo_db import seed_demo_database


TEST_DB_FILE = "test_demo_saas.db"
TEST_DB_URL = f"sqlite+aiosqlite:///{os.path.abspath(TEST_DB_FILE)}"


@pytest.fixture(scope="module", autouse=True)
def setup_test_database():
    """Seeds a fresh SQLite test database before running Phase 2 tests."""
    if os.path.exists(TEST_DB_FILE):
        os.remove(TEST_DB_FILE)

    asyncio.run(seed_demo_database(TEST_DB_URL))

    yield

    if os.path.exists(TEST_DB_FILE):
        try:
            os.remove(TEST_DB_FILE)
        except OSError:
            pass


@pytest_asyncio.fixture
async def db_engine():
    engine = DatabaseEngine(TEST_DB_URL, statement_timeout=5.0, read_only=True)
    yield engine
    await engine.close()


@pytest.mark.asyncio
async def test_inspect_schema(db_engine):
    """Verify that inspect_schema correctly reflects all tables, columns, PKs, FKs, and indexes."""
    graph: RelationshipGraph = await db_engine.inspect_schema()

    expected_tables = {"tenants", "users", "invoices", "transactions", "audit_events"}
    assert expected_tables.issubset(set(graph.tables.keys()))

    # Check tenants table
    tenants: TableSchema = graph.tables["tenants"]
    tenant_cols = {c.name for c in tenants.columns}
    assert {"id", "name", "domain", "status", "created_at"}.issubset(tenant_cols)
    assert "id" in tenants.primary_key

    # Check users table & Foreign Keys
    users: TableSchema = graph.tables["users"]
    user_cols = {c.name for c in users.columns}
    assert {"id", "tenant_id", "name", "email", "role"}.issubset(user_cols)

    fk_tenant = [fk for fk in users.foreign_keys if fk.referred_table == "tenants"]
    assert len(fk_tenant) == 1
    assert fk_tenant[0].constrained_columns == ["tenant_id"]

    # Check relationship edges
    edges = graph.foreign_key_edges
    assert any(e.source_table == "users" and e.target_table == "tenants" for e in edges)
    assert any(e.source_table == "invoices" and e.target_table == "users" for e in edges)


@pytest.mark.asyncio
async def test_execute_read_only_query(db_engine):
    """Verify that SELECT queries succeed and return structured dictionary rows."""
    rows = await db_engine.execute_query("SELECT name, domain FROM tenants ORDER BY id ASC")
    assert len(rows) == 4
    assert rows[0]["name"] == "Acme Corp"
    assert rows[1]["name"] == "Stark Industries"


@pytest.mark.asyncio
async def test_query_anomalous_transactions(db_engine):
    """Verify querying anomalous financial transactions."""
    sql = "SELECT id, amount, flags FROM transactions WHERE flags LIKE '%ANOMALOUS%' OR flags LIKE '%SUSPICIOUS%'"
    rows = await db_engine.execute_query(sql)
    assert len(rows) >= 2
    amounts = [float(r["amount"]) for r in rows]
    assert 2500000.0 in amounts or -5000.0 in amounts or 999999.99 in amounts


@pytest.mark.asyncio
async def test_read_only_enforcement_blocks_inserts(db_engine):
    """Verify that INSERT attempts trigger ReadOnlyViolationException."""
    with pytest.raises(ReadOnlyViolationException):
        await db_engine.execute_query("INSERT INTO tenants (name, domain) VALUES ('Hacker Corp', 'hacker.com')")


@pytest.mark.asyncio
async def test_read_only_enforcement_blocks_updates(db_engine):
    """Verify that UPDATE attempts trigger ReadOnlyViolationException."""
    with pytest.raises(ReadOnlyViolationException):
        await db_engine.execute_query("UPDATE users SET role = 'ADMIN' WHERE id = 2")


@pytest.mark.asyncio
async def test_read_only_enforcement_blocks_deletes(db_engine):
    """Verify that DELETE attempts trigger ReadOnlyViolationException."""
    with pytest.raises(ReadOnlyViolationException):
        await db_engine.execute_query("DELETE FROM audit_events WHERE id = 1")


@pytest.mark.asyncio
async def test_statement_timeout_cancellation():
    """Verify that queries exceeding the statement_timeout trigger QueryTimeoutException."""
    # Create engine with ultra-short timeout (0.001 seconds)
    short_engine = DatabaseEngine(TEST_DB_URL, statement_timeout=0.0001, read_only=True)
    try:
        # Recursive CTE or cross-join that takes more time than 0.0001s
        long_query = (
            "WITH RECURSIVE cnt(x) AS ("
            "  SELECT 1 UNION ALL SELECT x+1 FROM cnt WHERE x < 1000000"
            ") SELECT COUNT(*) FROM cnt c1 CROSS JOIN cnt c2;"
        )
        with pytest.raises(QueryTimeoutException):
            await short_engine.execute_query(long_query)
    finally:
        await short_engine.close()
