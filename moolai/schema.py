"""Creates indexes for a company graph. Safe to run repeatedly: `python -m moolai.schema`."""

from .config import settings
from .db import graph
from .queries import schema_statements


def ensure_schema(graph_name: str | None = None) -> int:
    """Apply queries/00_schema.cypher; returns how many indexes were newly created."""
    g = graph(graph_name)
    created = 0
    for stmt in schema_statements():
        try:
            g.query(stmt)
            created += 1
        except Exception as exc:  # index already exists
            if "already" not in str(exc).lower():
                raise
    return created


if __name__ == "__main__":
    n = ensure_schema()
    print(f"graph {settings.graph}: {n} new index(es)")
