"""Incremental sync on demand (the UI's "Sync now"): KEPs from git, then GitHub, in a background thread."""

import logging
import threading
import time

from .db import run

log = logging.getLogger("moolai.syncer")

_lock = threading.Lock()
_state: dict = {"running": False, "started_at": None, "finished_at": None, "result": None, "error": None}


def start() -> bool:
    """Start a sync unless one is running. Returns False if one already was."""
    with _lock:
        if _state["running"]:
            return False
        _state.update(running=True, started_at=int(time.time()), error=None)
    threading.Thread(target=_run, daemon=True).start()
    return True


def _run() -> None:
    from .ingest import keps, pulls

    try:
        result = {"keps": keps.sync(), **pulls.sync()}
        _state.update(result=result)
    except Exception as exc:  # surfaced in /api/sync/status
        log.exception("sync failed")
        _state.update(error=f"{type(exc).__name__}: {exc}")
    finally:
        _state.update(running=False, finished_at=int(time.time()))


def status() -> dict:
    return {**_state, "sources": run("sync_status", read_only=True)}
