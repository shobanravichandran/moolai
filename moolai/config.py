"""Runtime settings, read from environment variables (see /.env.example)."""

import os
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = REPO_ROOT / "config"
QUERY_DIR = REPO_ROOT / "queries"
DATA_DIR = REPO_ROOT / "data"

try:  # local dev; in Docker the env vars come from compose
    from dotenv import load_dotenv

    load_dotenv(REPO_ROOT / ".env")
except ImportError:
    pass


def _bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes"}


def _float(name: str) -> float | None:
    value = os.getenv(name, "").strip()
    return float(value) if value else None


def _path(name: str) -> str | None:
    value = os.getenv(name, "").strip()
    return str(REPO_ROOT / value) if value and not Path(value).is_absolute() else value or None


@dataclass(frozen=True)
class Settings:
    falkordb_host: str = os.getenv("FALKORDB_HOST", "localhost")
    falkordb_port: int = int(os.getenv("FALKORDB_PORT", "6380"))
    falkordb_username: str | None = os.getenv("FALKORDB_USERNAME") or None
    falkordb_password: str | None = os.getenv("FALKORDB_PASSWORD") or None
    falkordb_ssl: bool = _bool("FALKORDB_SSL")
    graph: str = os.getenv("MOOLAI_GRAPH", "brain_kubernetes")  # one graph per company

    github_token: str | None = os.getenv("GITHUB_TOKEN") or None
    model: str = os.getenv("MOOLAI_MODEL", "claude-opus-5-5")
    usage_ledger: str | None = _path("USAGE_LEDGER")

    # Hosted (Vercel) mode: no git/GitHub writes from requests, and a shared daily cap on Claude spend.
    read_only: bool = _bool("MOOLAI_READ_ONLY")
    daily_budget_usd: float | None = _float("MOOLAI_DAILY_BUDGET_USD")


settings = Settings()
