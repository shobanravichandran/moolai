"""Loads the named Cypher queries in queries/.

The .cypher files are the single source of truth: the code runs them by name, and the README links to the same
files for judges.
"""

from functools import cache

from .config import QUERY_DIR

SCHEMA_FILE = "00_schema"


def _strip_comments(text: str) -> str:
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("//")).strip()


@cache
def load_query(name: str) -> str:
    path = QUERY_DIR / f"{name}.cypher"
    if not path.is_file():
        raise KeyError(f"unknown query: {name}")
    return _strip_comments(path.read_text(encoding="utf-8"))


def query_source(name: str) -> str:
    """The .cypher file as written, comments included (shown in the UI's Query Inspector)."""
    if name not in all_query_names():
        raise KeyError(f"unknown query: {name}")
    return (QUERY_DIR / f"{name}.cypher").read_text(encoding="utf-8").strip()


def schema_statements() -> list[str]:
    return [stmt.strip() for stmt in load_query(SCHEMA_FILE).split(";") if stmt.strip()]


def all_query_names() -> list[str]:
    return sorted(p.stem for p in QUERY_DIR.glob("*.cypher") if p.stem != SCHEMA_FILE)
