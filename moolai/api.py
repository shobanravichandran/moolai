"""Moolai API (FastAPI). Locally: uvicorn moolai.api:app --reload --port 8020."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from .config import settings
from .db import get_db, run
from .queries import query_source
from .schema import ensure_schema

log = logging.getLogger("moolai")


@asynccontextmanager
async def lifespan(_: FastAPI):
    try:
        ensure_schema()
    except Exception as exc:  # keep the API up so /api/health can report the problem
        log.warning("schema not applied: %s", exc)
    yield


app = FastAPI(title="Moolai API", lifespan=lifespan)


@app.get("/api/health")
def health() -> dict:
    try:
        get_db().list_graphs()
        status = "ok"
    except Exception as exc:  # report, don't crash, so the check stays useful
        return {"ok": True, "falkordb": f"unreachable: {type(exc).__name__}", "graph": settings.graph}
    counts = {r["label"]: r["n"] for r in run("stats_counts", read_only=True)}
    return {"ok": True, "falkordb": status, "graph": settings.graph, "counts": counts}


@app.get("/api/cypher")
def cypher(name: str):
    try:
        return {"name": name, "cypher": query_source(name)}
    except KeyError:
        return JSONResponse(status_code=404, content={"detail": f"Unknown query: {name}"})
