"""Run against the disposable Compose database, not a production database."""
import os
import pytest
from core.database import DatabaseEngine, DatabaseEngineException

@pytest.mark.asyncio
@pytest.mark.skipif(not os.getenv("TEST_POSTGRES_URL"),reason="Disposable PostgreSQL server not configured")
async def test_postgres_pooled_readonly():
    engine=DatabaseEngine(os.environ["TEST_POSTGRES_URL"],read_only=True)
    try:
        for _ in range(3):
            assert await engine.execute_query("SELECT COUNT(*) AS n FROM users")
            with pytest.raises(DatabaseEngineException):
                await engine.execute_query("DELETE FROM users")
        assert "users" in (await engine.inspect_schema()).tables
    finally:
        await engine.close()
