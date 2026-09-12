"""
Sandboxed Database Connection Engine & Dynamic Schema Reflection using SQLAlchemy and Pydantic.
"""

import asyncio
from typing import Any, Dict, List, Optional, Tuple
from pydantic import BaseModel, Field
import sqlalchemy as sa
from sqlalchemy import event, inspect, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine


class DatabaseEngineException(Exception):
    """Base exception for database connection engine errors."""
    pass


class QueryTimeoutException(DatabaseEngineException):
    """Raised when a query exceeds the configured statement timeout."""
    pass


class ReadOnlyViolationException(DatabaseEngineException):
    """Raised when a write/mutation operation is attempted on a read-only session."""
    pass


class ColumnSchema(BaseModel):
    name: str
    type: str
    nullable: bool = True
    primary_key: bool = False
    default: Optional[str] = None


class ForeignKeySchema(BaseModel):
    constrained_columns: List[str]
    referred_table: str
    referred_columns: List[str]
    name: Optional[str] = None


class IndexSchema(BaseModel):
    name: str
    column_names: List[str]
    unique: bool = False


class TableSchema(BaseModel):
    name: str
    columns: List[ColumnSchema] = Field(default_factory=list)
    primary_key: List[str] = Field(default_factory=list)
    foreign_keys: List[ForeignKeySchema] = Field(default_factory=list)
    indexes: List[IndexSchema] = Field(default_factory=list)


class ForeignKeyEdge(BaseModel):
    source_table: str
    source_column: str
    target_table: str
    target_column: str
    constraint_name: Optional[str] = None


class RelationshipGraph(BaseModel):
    tables: Dict[str, TableSchema] = Field(default_factory=dict)
    foreign_key_edges: List[ForeignKeyEdge] = Field(default_factory=list)


class DatabaseEngine:
    """
    Asynchronous database abstraction layer providing sandboxed read-only query execution
    and dynamic schema introspection.
    """

    def __init__(
        self,
        db_url: str,
        statement_timeout: float = 5.0,
        read_only: bool = True,
    ):
        self.db_url = db_url
        self.statement_timeout = statement_timeout
        self.read_only = read_only

        connect_args: Dict[str, Any] = {}
        if "postgresql" in self.db_url:
            timeout_ms = str(int(self.statement_timeout * 1000))
            connect_args["server_settings"] = {"statement_timeout": timeout_ms}

        self.engine: AsyncEngine = create_async_engine(
            self.db_url,
            connect_args=connect_args,
            echo=False,
        )

        if self.read_only:
            self._configure_read_only_protection()

        self.session_factory = async_sessionmaker(
            bind=self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

    def _configure_read_only_protection(self) -> None:
        """Enforces read-only transaction isolation at the connection level."""
        sync_engine = self.engine.sync_engine

        if "sqlite" in self.db_url:
            @event.listens_for(sync_engine, "connect")
            def set_sqlite_readonly(dbapi_connection, connection_record):
                cursor = dbapi_connection.cursor()
                try:
                    cursor.execute("PRAGMA query_only = ON;")
                finally:
                    cursor.close()
        elif "postgresql" in self.db_url:
            @event.listens_for(sync_engine, "connect")
            def set_pg_readonly(dbapi_connection, connection_record):
                cursor = dbapi_connection.cursor()
                try:
                    cursor.execute("SET TRANSACTION READ ONLY;")
                finally:
                    cursor.close()

    async def inspect_schema(self) -> RelationshipGraph:
        """
        Programmatically introspects all tables, columns, primary keys,
        foreign keys, and indexes, returning a structured RelationshipGraph.
        """
        def _sync_inspect(sync_conn):
            inspector = inspect(sync_conn)
            table_names = inspector.get_table_names()

            tables_dict: Dict[str, TableSchema] = {}
            edges: List[ForeignKeyEdge] = []

            for tname in table_names:
                cols_raw = inspector.get_columns(tname)
                pk_raw = inspector.get_pk_constraint(tname)
                fks_raw = inspector.get_foreign_keys(tname)
                indexes_raw = inspector.get_indexes(tname)

                pk_cols = set(pk_raw.get("constrained_columns", [])) if pk_raw else set()

                columns: List[ColumnSchema] = []
                for c in cols_raw:
                    columns.append(
                        ColumnSchema(
                            name=c["name"],
                            type=str(c["type"]),
                            nullable=c.get("nullable", True),
                            primary_key=c["name"] in pk_cols,
                            default=str(c["default"]) if c.get("default") is not None else None,
                        )
                    )

                foreign_keys: List[ForeignKeySchema] = []
                for fk in fks_raw:
                    constrained = fk.get("constrained_columns", [])
                    referred_tbl = fk.get("referred_table", "")
                    referred_cols = fk.get("referred_columns", [])
                    fk_name = fk.get("name")

                    foreign_keys.append(
                        ForeignKeySchema(
                            constrained_columns=constrained,
                            referred_table=referred_tbl,
                            referred_columns=referred_cols,
                            name=fk_name,
                        )
                    )

                    for src_col, target_col in zip(constrained, referred_cols):
                        edges.append(
                            ForeignKeyEdge(
                                source_table=tname,
                                source_column=src_col,
                                target_table=referred_tbl,
                                target_column=target_col,
                                constraint_name=fk_name,
                            )
                        )

                indexes: List[IndexSchema] = []
                for idx in indexes_raw:
                    indexes.append(
                        IndexSchema(
                            name=idx.get("name") or "",
                            column_names=idx.get("column_names", []),
                            unique=idx.get("unique", False),
                        )
                    )

                tables_dict[tname] = TableSchema(
                    name=tname,
                    columns=columns,
                    primary_key=list(pk_cols),
                    foreign_keys=foreign_keys,
                    indexes=indexes,
                )

            return RelationshipGraph(tables=tables_dict, foreign_key_edges=edges)

        async with self.engine.connect() as conn:
            return await conn.run_sync(_sync_inspect)

    async def execute_query(self, sql_query: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """
        Executes a candidate read-only SQL query with statement timeout protection.

        Returns:
            List of dictionary rows.

        Raises:
            QueryTimeoutException: If execution time exceeds statement_timeout.
            ReadOnlyViolationException: If query attempts database modification.
            DatabaseEngineException: For other execution errors.
        """
        async def _run():
            async with self.engine.connect() as conn:
                result = await conn.execute(text(sql_query), params or {})
                if result.returns_rows:
                    mappings = result.mappings().all()
                    return [dict(row) for row in mappings]
                return []

        try:
            return await asyncio.wait_for(_run(), timeout=self.statement_timeout)
        except asyncio.TimeoutError as exc:
            raise QueryTimeoutException(
                f"Query execution timed out after {self.statement_timeout} seconds."
            ) from exc
        except sa.exc.OperationalError as exc:
            err_msg = str(exc).lower()
            if "readonly" in err_msg or "read-only" in err_msg or "cannot execute" in err_msg:
                raise ReadOnlyViolationException(f"Write operation rejected in read-only sandbox: {exc}") from exc
            raise DatabaseEngineException(f"Database operational error: {exc}") from exc
        except Exception as exc:
            raise DatabaseEngineException(f"Failed to execute query: {exc}") from exc

    async def close(self) -> None:
        """Close the underlying database engine connection pool."""
        await self.engine.dispose()
