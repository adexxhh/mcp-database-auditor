"""Measure local schema/guardrail latency; never hard-code performance claims."""
import argparse,asyncio,json,statistics,tempfile,time
from pathlib import Path
from core.database import DatabaseEngine
from security.guardrail import SQLGuardrail
from scripts.seed_demo_db import seed_demo_database

async def measure(repeats):
    with tempfile.TemporaryDirectory() as temp:
        url="sqlite+aiosqlite:///"+(Path(temp)/"demo.db").as_posix()
        await seed_demo_database(url)
        engine=DatabaseEngine(url)
        try:
            schema=[];guard=[]
            validator=SQLGuardrail()
            for _ in range(repeats):
                start=time.perf_counter();await engine.inspect_schema()
                schema.append((time.perf_counter()-start)*1000)
                start=time.perf_counter();validator.validate("SELECT name FROM users")
                guard.append((time.perf_counter()-start)*1000)
            def stats(xs):return {"p50_ms":statistics.median(xs),"p95_ms":sorted(xs)[max(0,__import__("math").ceil(.95*len(xs))-1)]}
            return {"scope":"local seeded SQLite, warm pool after first sample","repeats":repeats,
                    "schema":stats(schema),"guardrail":stats(guard),"samples_ms":{"schema":schema,"guardrail":guard}}
        finally:await engine.close()

if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--repeats",type=int,default=30);p.add_argument("--output")
    args=p.parse_args()
    if args.repeats<2:p.error("At least two repetitions are required")
    report=asyncio.run(measure(args.repeats));out=json.dumps(report,indent=2)
    if args.output:Path(args.output).write_text(out,encoding="utf-8")
    print(out)
