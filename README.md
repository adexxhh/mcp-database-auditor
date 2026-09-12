# mcp-database-auditor

Production-grade Model Context Protocol (MCP) server for database auditing and deterministic SQL guardrails.

## Features

### Phase 1: Deterministic SQL Guardrail and AST Validator
- **SQL AST Verification**: Uses `sqlglot` to parse and validate SQL queries against PostgreSQL syntax.
- **Strict Read-Only Enforcement**: Accepts only single-statement `SELECT` queries (including CTEs, subqueries, and joins). Blocks destructive DDL and DML commands (`DROP`, `UPDATE`, `DELETE`, `INSERT`, `ALTER`, `TRUNCATE`, `CREATE`, `GRANT`, multi-statement queries).
- **Comment Stripping & Injection Defense**: Strips out inline SQL comments (`--`, `/* */`) that could mask commands or hide injection vectors.
- **Resource Control**:
  - Automatically appends `LIMIT 100` if no `LIMIT` clause is present.
  - Clamps explicit `LIMIT` values > 1,000 down to `1,000`.
- **Structured Exceptions**: Exports `UnsafeQueryException`, `DisallowedCommandException`, and `ASTParsingException`.

## Usage

```python
from security.guardrail import SQLGuardrail, UnsafeQueryException

guardrail = SQLGuardrail(default_limit=100, max_limit=1000)

# Valid read-only query (automatically receives LIMIT 100)
safe_sql = guardrail.validate_and_transform("SELECT * FROM users WHERE active = true")
print(safe_sql)
# -> SELECT * FROM users WHERE active = true LIMIT 100

# Destructive commands are blocked
try:
    guardrail.validate_and_transform("DROP TABLE users")
except UnsafeQueryException as e:
    print(f"Blocked: {e}")
```

## Running Tests

```bash
pytest tests/
```
