# Engineering changes and project ownership

## A defensible description
"I built a local MCP prototype that exposes schema inspection, guarded read-only queries, sampled data profiles, query-plan diagnostics and schema snapshots. I use SQL parsing plus database restrictions, test malicious nested SQL and measure local latency. PostgreSQL deployment verification remains separate."

The scope is a database tool server. It does not train a model, authenticate enterprise tenants or guarantee that all SQL is harmless.

## Trace the implementation
1. Read server.py: decorators expose MCP tools/resources; ensure_database initializes a missing local demo without starting another event loop.
2. Follow execute_safe_query into security/guardrail.py. Parsing produces an expression tree, not just keyword matches.
3. Follow core/database.py into the async connection pool. The query is run in a transaction with database-specific restrictions.
4. Trace row conversion, fingerprinting and JSONL audit recording.
5. Follow analyze_query_plan: policy-check the SQL, ask the actual DB for EXPLAIN output, then identify candidate full scans.
6. Trace core/profiler.py. Reported null rates and outliers describe the returned sample only.
7. Use client_test.py to see the real MCP initialize/list-tools/read-resource/call-tool protocol.

## Before and after
| Earlier issue | Repair | Engineering consequence |
|---|---|---|
| Missing asyncio dependency and ambiguous package discovery | Explicit SQLAlchemy asyncio extra, asyncpg dependency and setuptools packages | Clean installs can import the database layer |
| First call could invoke asyncio.run inside an existing event loop | Awaited initialization under a lock | Resource access works on a fresh checkout |
| Root-only SQL checks missed nested mutations | Inspect descendants, INTO, locks and functions | SELECT syntax is no longer confused with guaranteed read-only semantics |
| LIMIT expressions could bypass clamping | Reject non-literal/negative limits | Output bounds are explicit; this still does not bound query work |
| Read-only PostgreSQL set on initial pool connect | Set inside every query transaction | Returning a connection to the pool does not silently define later transaction policy |
| SQLite cancellation could leave CPU work running | SQLite progress-handler deadline as well as async timeout | The database has a way to stop expensive computation |
| JSON/list columns could break cardinality profiling; Decimal ignored | Stable serialized cardinality keys and Decimal numeric handling | Real database values are handled more consistently |
| Audit/fingerprint and schema-diff claims lacked implementation | Literal-redacted normalized fingerprints, JSONL records, in-process snapshots | The claims now point to concrete code and tests |
| Unindexed-FK heuristic treated any composite-index column as useful | Consider leading index columns | Fewer misleading index recommendations; still a heuristic |
| Claimed full-scan detection lacked plan analysis | Actual EXPLAIN inspection | Diagnostics use the planner rather than guessing solely from SQL text |

## Concepts to master
**MCP:** tools execute actions, resources expose readable context, prompts supply reusable templates. Explain initialization, tool discovery, stdio transport and why protocol stdout must remain clean.

**SQL ASTs:** parse a modifying CTE under a SELECT root. Explain why comments and strings make regex security unreliable. Explain why SELECT can call side-effecting functions and why a function policy is conservative.

**Database boundaries:** a SELECT-only role, read-only transaction and parser policy serve different purposes. Explain connection pools, transaction rollback/reset and why a connect hook is not a per-transaction hook.

**Query cost:** LIMIT caps returned rows, not necessarily scanned rows, joins, aggregation or sorting. EXPLAIN without ANALYZE asks for a plan; EXPLAIN ANALYZE executes. A sequential scan can be the correct plan for a small table.

**Statistics:** null rate = null count / sampled row count; cardinality counts distinct values in that sample. Understand IQR, population versus sample standard deviation, small-sample limitations and why the first 100 rows are a biased sample.

**Measurement:** median versus p95, cold versus warm connections, number of tables, schema size, storage/network conditions and repeat count. The recorded ~15 ms schema result applies to local SQLite only.

**Audit design:** normalize literal values before fingerprinting. A fingerprint groups similar queries; it is not a log of the original values or a proof of schema history. Local JSONL needs rotation/centralization for sustained deployment.

## Hands-on ownership checkpoints
- Start from a fresh temporary directory and explain every request in the stdio harness.
- Add a legitimate SQL function to the allowlist and add an adversarial function test.
- Show a nested DELETE rejection and explain which AST node caused it.
- Compare EXPLAIN output for a full scan and a primary-key lookup.
- Create two new tables in a separate writable fixture, take snapshots and inspect the diff.
- Profile a JSON/Decimal/null fixture and calculate the expected summary manually.
- Change the row cap and explain the effect on profiling versus database query cost.
- Re-run benchmark.py and report hardware, fixture, repetitions and percentiles.

## Verification and limits
58 CPU tests passed; real stdio integration passed. A PostgreSQL integration test is present but skipped locally because no server/Docker is available. CI provisioned a disposable PostgreSQL service and its pooled read-only integration job passed; docs/evidence/github-actions.json records the immutable run. SSE is for trusted local use. There is no OS sandbox, tenant authorization, representative large-table profiling or centralized durable audit store.

Do not call this enterprise production-ready or describe the SQLite timing as PostgreSQL performance. Those are future verification and engineering tasks.
