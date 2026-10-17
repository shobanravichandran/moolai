import uuid

import pytest

from moolai.db import get_db
from moolai.queries import all_query_names, load_query
from moolai.schema import ensure_schema


def _falkordb_up() -> bool:
    try:
        get_db().connection.ping()
        return True
    except Exception:
        return False


def test_named_queries_load():
    for name in all_query_names():
        assert load_query(name)


@pytest.mark.db
@pytest.mark.skipif(not _falkordb_up(), reason="FalkorDB is not reachable")
def test_schema_is_idempotent():
    name = f"test_schema_{uuid.uuid4().hex[:8]}"
    try:
        assert ensure_schema(name) > 0
        assert ensure_schema(name) == 0
    finally:
        get_db().select_graph(name).delete()
