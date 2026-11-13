"""AZ-FF1: SQL query counter for N+1 regression testing.

Provides a context manager that counts SQLAlchemy statements executed
within a block, so tests can assert an upper bound on query count per
endpoint (zero-N+1 tolerance).
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import event

from app.extensions import db


@contextmanager
def count_queries() -> Iterator[QueryCounter]:
    """Context manager counting DB statements.

    Usage::

        with count_queries() as qc:
            client.get("/api/v1/grades")
        assert qc.count <= 5
    """
    counter = QueryCounter()
    engine = db.engine

    def _before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        counter.count += 1
        counter.statements.append(statement)

    event.listen(engine, "before_cursor_execute", _before_cursor_execute)
    try:
        yield counter
    finally:
        event.remove(engine, "before_cursor_execute", _before_cursor_execute)


class QueryCounter:
    def __init__(self) -> None:
        self.count: int = 0
        self.statements: list[str] = []
