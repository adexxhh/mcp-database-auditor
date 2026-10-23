import pytest_asyncio
import server
from scripts.seed_demo_db import seed_demo_database

@pytest_asyncio.fixture(autouse=True)
async def isolated_server(tmp_path, monkeypatch):
    db_url = "sqlite+aiosqlite:///" + (tmp_path / "demo.db").as_posix()
    await seed_demo_database(db_url)
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setenv("AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))
    server._db_engine = None
    server._previous_schema = None
    yield
    if server._db_engine:
        await server._db_engine.close()
    server._db_engine = None
