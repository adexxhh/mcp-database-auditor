import pytest
from security.guardrail import (
    SQLGuardrail,
    UnsafeQueryException,
    DisallowedCommandException,
    ASTParsingException,
)


@pytest.fixture
def guardrail():
    return SQLGuardrail(default_limit=100, max_limit=1000)


def test_exception_hierarchy():
    """Verify that custom exceptions inherit from UnsafeQueryException."""
    assert issubclass(DisallowedCommandException, UnsafeQueryException)
    assert issubclass(ASTParsingException, UnsafeQueryException)


def test_valid_simple_select_limit_injection(guardrail):
    """Simple SELECT without LIMIT should have LIMIT 100 appended."""
    query = "SELECT * FROM users"
    result = guardrail.validate_and_transform(query)
    assert "LIMIT 100" in result
    assert "SELECT * FROM users" in result


def test_valid_select_with_joins(guardrail):
    """SELECT with JOINs should pass and receive automatic LIMIT 100."""
    query = (
        "SELECT u.id, u.name, o.total "
        "FROM users u "
        "JOIN orders o ON u.id = o.user_id "
        "WHERE o.status = 'completed'"
    )
    result = guardrail.validate_and_transform(query)
    assert "LIMIT 100" in result
    assert "JOIN orders" in result


def test_valid_subqueries(guardrail):
    """SELECT with subquery should pass and receive top-level LIMIT 100."""
    query = "SELECT * FROM (SELECT id, name FROM users WHERE active = true) AS active_users"
    result = guardrail.validate_and_transform(query)
    assert "LIMIT 100" in result


def test_valid_cte_query(guardrail):
    """CTEs (WITH ... SELECT) should pass and receive appropriate LIMIT clause."""
    query = (
        "WITH active_users AS ("
        "  SELECT id, email FROM users WHERE status = 'active'"
        ") "
        "SELECT id, email FROM active_users"
    )
    result = guardrail.validate_and_transform(query)
    assert "LIMIT 100" in result
    assert "WITH active_users AS" in result


def test_valid_union_query(guardrail):
    """UNION of SELECT statements should pass and receive LIMIT clause."""
    query = "SELECT id, name FROM employees UNION SELECT id, name FROM contractors"
    result = guardrail.validate_and_transform(query)
    assert "LIMIT 100" in result
    assert "UNION" in result


def test_existing_limit_below_max_preserved(guardrail):
    """Existing LIMIT <= 1000 should be preserved."""
    query = "SELECT * FROM users LIMIT 50"
    result = guardrail.validate_and_transform(query)
    assert "LIMIT 50" in result


def test_existing_limit_exceeding_max_clamped(guardrail):
    """Existing LIMIT > 1000 should be clamped to 1000."""
    query = "SELECT * FROM users LIMIT 5000"
    result = guardrail.validate_and_transform(query)
    assert "LIMIT 1000" in result
    assert "LIMIT 5000" not in result


def test_subquery_and_cte_limit_clamping(guardrail):
    """LIMIT clauses in CTEs or subqueries exceeding 1000 should also be clamped to 1000."""
    query = "WITH large_cte AS (SELECT * FROM logs LIMIT 10000) SELECT * FROM large_cte LIMIT 500"
    result = guardrail.validate_and_transform(query)
    assert "LIMIT 1000" in result
    assert "LIMIT 500" in result
    assert "LIMIT 10000" not in result


def test_comment_stripping_single_line(guardrail):
    """Inline single-line comments (-- ...) should be stripped."""
    query = "SELECT * FROM users WHERE age > 21 -- filter adults"
    result = guardrail.validate_and_transform(query)
    assert "-- filter adults" not in result
    assert "filter adults" not in result
    assert "LIMIT 100" in result


def test_comment_stripping_multi_line(guardrail):
    """Inline multi-line comments (/* ... */) should be stripped."""
    query = "SELECT /* mask column */ id, name FROM users /* table comment */"
    result = guardrail.validate_and_transform(query)
    assert "/* mask column */" not in result
    assert "/* table comment */" not in result
    assert "LIMIT 100" in result


def test_block_drop_table(guardrail):
    """DROP TABLE should be completely blocked."""
    with pytest.raises(DisallowedCommandException) as exc_info:
        guardrail.validate_and_transform("DROP TABLE users")
    assert "Disallowed SQL command" in str(exc_info.value) or "DROP" in str(exc_info.value)


def test_block_update(guardrail):
    """UPDATE should be completely blocked."""
    with pytest.raises(DisallowedCommandException) as exc_info:
        guardrail.validate_and_transform("UPDATE users SET is_admin = true WHERE id = 1")
    assert "Disallowed SQL command" in str(exc_info.value) or "UPDATE" in str(exc_info.value)


def test_block_delete(guardrail):
    """DELETE should be completely blocked."""
    with pytest.raises(DisallowedCommandException):
        guardrail.validate_and_transform("DELETE FROM users WHERE id = 10")


def test_block_insert(guardrail):
    """INSERT should be completely blocked."""
    with pytest.raises(DisallowedCommandException):
        guardrail.validate_and_transform("INSERT INTO users (name) VALUES ('hacker')")


def test_block_truncate(guardrail):
    """TRUNCATE should be completely blocked."""
    with pytest.raises(DisallowedCommandException):
        guardrail.validate_and_transform("TRUNCATE TABLE audit_logs")


def test_block_create(guardrail):
    """CREATE TABLE should be completely blocked."""
    with pytest.raises(DisallowedCommandException):
        guardrail.validate_and_transform("CREATE TABLE backdoor (id INT)")


def test_block_alter(guardrail):
    """ALTER TABLE should be completely blocked."""
    with pytest.raises(DisallowedCommandException):
        guardrail.validate_and_transform("ALTER TABLE users ADD COLUMN password_hash TEXT")


def test_block_grant(guardrail):
    """GRANT should be completely blocked."""
    with pytest.raises(UnsafeQueryException):
        guardrail.validate_and_transform("GRANT ALL ON users TO PUBLIC")


def test_block_multi_statement(guardrail):
    """Multi-statement queries (e.g. SELECT 1; DELETE FROM users) must be blocked."""
    query = "SELECT 1; DELETE FROM users"
    with pytest.raises(DisallowedCommandException) as exc_info:
        guardrail.validate_and_transform(query)
    assert "Multi-statement" in str(exc_info.value)


def test_empty_query_raises_ast_parsing_exception(guardrail):
    """Empty string or whitespace-only query should raise ASTParsingException."""
    with pytest.raises(ASTParsingException):
        guardrail.validate_and_transform("")

    with pytest.raises(ASTParsingException):
        guardrail.validate_and_transform("   \n\t  ")


def test_invalid_syntax_raises_ast_parsing_exception(guardrail):
    """Syntactically broken query should raise ASTParsingException."""
    with pytest.raises(ASTParsingException):
        guardrail.validate_and_transform("SELECT FROM WHERE ???")


def test_aliases_work(guardrail):
    """verify_query and validate aliases should function identically."""
    sql = "SELECT * FROM products"
    assert guardrail.verify_query(sql) == guardrail.validate_and_transform(sql)
    assert guardrail.validate(sql) == guardrail.validate_and_transform(sql)
