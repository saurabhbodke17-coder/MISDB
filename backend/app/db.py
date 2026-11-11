from contextlib import contextmanager

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from .config import settings

pool: ConnectionPool | None = None
source_pool: ConnectionPool | None = None


def start_pool():
    global pool, source_pool
    pool = ConnectionPool(
        settings().database_url,
        min_size=1,
        max_size=10,
        timeout=10,
        kwargs={"row_factory": dict_row, "options": "-c timezone=Asia/Kolkata -c statement_timeout=15000"},
        open=True,
    )
    pool.wait(timeout=15)
    if settings().source_database_url:
        source_pool = ConnectionPool(
            settings().source_database_url,
            min_size=1,
            max_size=10,
            timeout=10,
            kwargs={
                "row_factory": dict_row,
                "options": (
                    '-c default_transaction_read_only=on -c search_path="LMS",public '
                    "-c timezone=Asia/Kolkata -c statement_timeout=15000"
                ),
            },
            open=True,
        )
        source_pool.wait(timeout=15)


@contextmanager
def connection():
    if pool is None:
        raise RuntimeError("Database pool is not initialized")
    with pool.connection() as conn:
        yield conn


def _uses_app_database(sql: str) -> bool:
    """Keep application-owned/authentication data local; route academic reads live."""
    return "mis." in sql.lower()


@contextmanager
def read_connection(sql: str):
    if settings().source_database_url and source_pool is None and not _uses_app_database(sql):
        raise RuntimeError("Production database pool is unavailable; local fallback is disabled")
    selected_pool = pool if _uses_app_database(sql) or source_pool is None else source_pool
    if selected_pool is None:
        raise RuntimeError("Database pool is not initialized")
    with selected_pool.connection() as conn:
        yield conn


def query(sql, params=None):
    with read_connection(sql) as conn:
        return conn.execute(sql, params or {}).fetchall()


def one(sql, params=None):
    rows = query(sql, params)
    return rows[0] if rows else None
