"""GitHub GraphQL client: rate-limit aware, retrying, and caching every response on disk.

Every response is written to data/raw/github/<sha256 of query + variables>.json.gz, so the graph can be
rebuilt without a token: `python -m moolai.ingest.pulls --offline` replays the cache (shipped as a release
asset).
"""

import gzip
import hashlib
import json
import logging
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

from ..config import DATA_DIR, settings

log = logging.getLogger("moolai.github")

ENDPOINT = "https://api.github.com/graphql"
CACHE_DIR = DATA_DIR / "raw" / "github"
RATE_LIMIT = "rateLimit { cost remaining resetAt }"


class GitHubError(RuntimeError):
    pass


class GitHub:
    def __init__(self, token: str | None = None, *, cache_dir: Path = CACHE_DIR):
        self.cache_dir = cache_dir
        self.token = token or settings.github_token
        if not self.token:
            raise GitHubError("GITHUB_TOKEN is not set: add it to .env (see .env.example), or use --offline")
        self.http = httpx.Client(timeout=90)
        self.calls = 0
        self.cost = 0

    def query(self, query: str, variables: dict | None = None, *, retries: int = 4) -> dict:
        """Run a query and return its `data`. Queries should select rateLimit so pacing works."""
        variables = variables or {}
        path = self.cache_dir / f"{_key(query, variables)}.json.gz"
        for attempt in range(retries + 1):
            try:
                body = self._post(query, variables)
                break
            except (httpx.TransportError, _Retryable) as exc:
                if attempt == retries:
                    raise GitHubError(f"GraphQL failed after {retries + 1} attempts: {exc}") from exc
                wait = 2**attempt * 3
                log.warning("GraphQL attempt %d failed (%s); retrying in %ds", attempt + 1, exc, wait)
                time.sleep(wait)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(gzip.compress(json.dumps(body).encode()))
        self._pace(body["data"].get("rateLimit"))
        return body["data"]

    def _post(self, query: str, variables: dict) -> dict:
        r = self.http.post(
            ENDPOINT,
            json={"query": query, "variables": variables},
            headers={"Authorization": f"bearer {self.token}"},
        )
        self.calls += 1
        if r.status_code in (502, 503, 504) or (r.status_code == 403 and "secondary rate" in r.text.lower()):
            raise _Retryable(f"HTTP {r.status_code}")
        if r.status_code == 401:
            raise GitHubError("GitHub rejected the token (401)")
        r.raise_for_status()
        body = r.json()
        if body.get("errors"):
            message = "; ".join(e.get("message", "?") for e in body["errors"])
            if body.get("data") is None or "timeout" in message.lower():
                raise _Retryable(message)
            log.warning("GraphQL partial errors: %s", message)  # e.g. a deleted PR in an aliased batch
        return body

    def _pace(self, rate: dict | None) -> None:
        if not rate:
            return
        self.cost += rate["cost"]
        if rate["remaining"] < max(50, rate["cost"] * 3):
            reset = datetime.fromisoformat(rate["resetAt"].replace("Z", "+00:00"))
            wait = max(0.0, (reset - datetime.now(UTC)).total_seconds()) + 5
            log.warning("GraphQL budget low (%d left); sleeping %.0fs until reset", rate["remaining"], wait)
            time.sleep(wait)


class _Retryable(Exception):
    pass


def _key(query: str, variables: dict) -> str:
    return hashlib.sha256((query + json.dumps(variables, sort_keys=True)).encode()).hexdigest()[:32]
