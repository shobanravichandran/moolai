"""FalkorDB access. One graph per company; every query is a named file in queries/."""

import time
from contextvars import ContextVar
from functools import lru_cache
from typing import Any

from falkordb import FalkorDB, Graph

from .config import settings
from .queries import load_query

# Per-request log of executed named queries, shown in the UI's Query Inspector.
query_log: ContextVar[list[dict] | None] = ContextVar("query_log", default=None)


@lru_cache(maxsize=1)
def get_db() -> FalkorDB:
    return FalkorDB(
        host=settings.falkordb_host,
        port=settings.falkordb_port,
        username=settings.falkordb_username,
        password=settings.falkordb_password,
        ssl=settings.falkordb_ssl,
    )


def graph(name: str | None = None) -> Graph:
    return get_db().select_graph(name or settings.graph)


def _column_name(col: Any) -> str:
    # Header entries are (name, type) pairs; pick the string to stay order-agnostic.
    if isinstance(col, (list, tuple)):
        return next(str(x) for x in col if isinstance(x, str))
    return str(col)


def _rows(result) -> list[dict]:
    names = [_column_name(c) for c in result.header]
    return [dict(zip(names, row, strict=True)) for row in result.result_set]


def run(
    name: str, params: dict | None = None, *, read_only: bool = False, graph_name: str | None = None
) -> list[dict]:
    """Run a named query and return rows as dicts."""
    g = graph(graph_name)
    query = load_query(name)
    start = time.perf_counter()
    result = g.ro_query(query, params) if read_only else g.query(query, params)
    log = query_log.get()
    if log is not None:
        log.append({"name": name, "ms": round((time.perf_counter() - start) * 1000, 1)})
    return _rows(result)
