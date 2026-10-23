"""Run a real local demo; values below are computed, not scripted results."""
import asyncio,json,tempfile,os
from pathlib import Path
import server
from scripts.seed_demo_db import seed_demo_database

async def main():
    with tempfile.TemporaryDirectory() as temporary:
        db=Path(temporary)/"demo.db"
        await seed_demo_database("sqlite+aiosqlite:///"+db.as_posix())
        os.environ["DATABASE_URL"]="sqlite+aiosqlite:///"+db.as_posix()
        os.environ["AUDIT_LOG_PATH"]=str(Path(temporary)/"audit.jsonl")
        print("MCP tools: SQL inspection, profiling, query plans, schema snapshots")
        graph=await server.get_current_schema()
        print("Reflected tables:",", ".join(sorted(json.loads(graph)["tables"])))
        safe=await server.execute_safe_query("SELECT name FROM users WHERE id=1")
        print("Read-only query:", "PASS" if "Query Execution Results" in safe else "FAIL")
        rejected=await server.execute_safe_query("WITH x AS (DELETE FROM users RETURNING *) SELECT * FROM x")
        print("Nested DELETE rejected:", "PASS" if "REJECTION" in rejected else "FAIL")
        plan=json.loads(await server.analyze_query_plan("SELECT name FROM users"))
        print("Real SQLite planner:",plan["full_scan_candidates"])
        print("Schema baseline:",await server.schema_changes())
        print("Repeat schema diff:",await server.schema_changes())
        print("Audit entries:",len(Path(os.environ["AUDIT_LOG_PATH"]).read_text().splitlines()))
        await server.get_engine().close()
        server._db_engine=None

if __name__=="__main__":asyncio.run(main())
