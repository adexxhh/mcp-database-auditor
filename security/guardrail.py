"""
Deterministic SQL Guardrail and AST Validator for PostgreSQL queries using sqlglot.
"""

from typing import Optional
import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError, ParseError, TokenError


class UnsafeQueryException(Exception):
    """Base exception for unsafe or disallowed SQL queries."""
    pass


class DisallowedCommandException(UnsafeQueryException):
    """Raised when a non-SELECT statement or disallowed SQL command is detected."""
    pass


class ASTParsingException(UnsafeQueryException):
    """Raised when SQL query parsing fails or input is invalid."""
    pass


class SQLGuardrail:
    """
    Deterministic SQL Guardrail that verifies SQL candidate queries against PostgreSQL
    AST safety invariants and enforces resource bounds (LIMIT controls).
    """

    DEFAULT_LIMIT = 100
    MAX_LIMIT = 1000

    def __init__(
        self,
        default_limit: int = DEFAULT_LIMIT,
        max_limit: int = MAX_LIMIT,
        dialect: str = "postgres",
    ):
        self.default_limit = default_limit
        self.max_limit = max_limit
        self.dialect = dialect

    def validate_and_transform(self, sql: str) -> str:
        """
        Verifies a candidate SQL query, strips inline comments, enforces AST invariants,
        applies resource LIMITs, and returns the sanitized SQL string.

        Args:
            sql: The input SQL query string.

        Returns:
            Sanitized PostgreSQL query string.

        Raises:
            ASTParsingException: If parsing fails or query is empty.
            DisallowedCommandException: If query contains disallowed commands or multiple statements.
            UnsafeQueryException: For other query safety violations.
        """
        if not sql or not isinstance(sql, str) or not sql.strip():
            raise ASTParsingException("Query string cannot be empty.")

        try:
            statements = sqlglot.parse(sql, read=self.dialect)
        except (ParseError, TokenError, SqlglotError, Exception) as e:
            raise ASTParsingException(f"Failed to parse SQL query: {e}") from e

        statements = [s for s in statements if s is not None]

        if not statements:
            raise ASTParsingException("Query contains no valid SQL statements.")

        if len(statements) > 1:
            raise DisallowedCommandException("Multi-statement queries are not allowed.")

        root = statements[0]

        # Explicitly check for disallowed DDL/DML node types
        disallowed_types = (
            exp.Insert,
            exp.Update,
            exp.Delete,
            exp.Drop,
            exp.Alter,
            exp.TruncateTable,
            exp.Create,
            exp.Grant,
            exp.Command,
        )
        if any(isinstance(node, disallowed_types) for node in root.walk()):
            cmd_name = root.key.upper() if hasattr(root, "key") and root.key else root.__class__.__name__
            raise DisallowedCommandException(f"Disallowed SQL command: {cmd_name}")

        # Root expression invariant: Must strictly resolve to a SELECT query (Select or Union)
        if not isinstance(root, (exp.Select, exp.Union)):
            raise DisallowedCommandException(
                f"Statement type '{root.__class__.__name__}' is not allowed. Query must be a SELECT statement."
            )

        # SELECT roots can still contain writes, row locks, or side-effecting functions.
        if root.find(exp.Into) or root.find(exp.Lock):
            raise DisallowedCommandException("SELECT INTO and locking clauses are not allowed.")
        allowed_functions = {
            "abs", "avg", "cast", "ceil", "ceiling", "coalesce", "concat", "count",
            "date", "date_trunc", "extract", "floor", "greatest", "least", "length",
            "lower", "max", "min", "nullif", "round", "row_number", "sum", "upper",
            "lag", "lead", "rank", "dense_rank", "substring", "trim", "current_date",
            "current_timestamp", "and", "or", "exists", "json_extract", "json_extract_scalar", "j_s_o_n_b_contains_top_key"
        }
        for node in root.find_all(exp.Func):
            name = node.name.lower() if isinstance(node, exp.Anonymous) else node.sql_name().lower()
            if name not in allowed_functions:
                raise DisallowedCommandException(f"Function '{name}' is not allowlisted.")
        for offset in root.find_all(exp.Offset):
            value = offset.expression
            if not isinstance(value, exp.Literal) or not value.is_int or int(value.this) < 0:
                raise UnsafeQueryException("OFFSET must be a non-negative integer literal.")

        # Strip all inline SQL comments (-- and /* */)
        for node in root.walk():
            node.comments = None

        # Automatic LIMIT Injection if lacking an explicit LIMIT clause on top-level query
        if root.args.get("limit") is None:
            root = root.limit(self.default_limit)

        # Max Row Bound Clamping across all LIMIT clauses (top-level, CTEs, subqueries)
        for limit_node in root.find_all(exp.Limit):
            try:
                val_expr = limit_node.expression
                if isinstance(val_expr, exp.Literal) and val_expr.is_int:
                    val = int(val_expr.this)
                else:
                    val = int(str(val_expr))

                if val < 0:
                    raise UnsafeQueryException("LIMIT must not be negative.")
                if val > self.max_limit:
                    limit_node.set("expression", exp.Literal.number(self.max_limit))
            except (ValueError, TypeError) as exc:
                raise UnsafeQueryException("LIMIT must be a bounded integer literal.") from exc

        return root.sql(dialect=self.dialect)

    def verify_query(self, sql: str) -> str:
        """Alias for validate_and_transform."""
        return self.validate_and_transform(sql)

    def validate(self, sql: str) -> str:
        """Alias for validate_and_transform."""
        return self.validate_and_transform(sql)
