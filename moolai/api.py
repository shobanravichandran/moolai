"""Moolai API (FastAPI). Locally: uvicorn moolai.api:app --reload --port 8020."""

import logging
from collections.abc import Callable
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from . import agent, brain, llm
from .config import settings
from .db import get_db, query_log, run
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


@app.exception_handler(brain.NotFound)
async def not_found(_: Request, exc: brain.NotFound) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": str(exc)})


def _with_queries(fn: Callable[..., dict], *args: Any, **kwargs: Any) -> dict:
    """Run fn; attach the named Cypher queries it ran (the UI's Query Inspector) and any model cost."""
    q_token = query_log.set([])
    u_token = llm.usage_log.set([])
    try:
        result = fn(*args, **kwargs)
        result["queries"] = query_log.get()
        result["usage"] = llm.summarize(llm.usage_log.get())
        return result
    finally:
        query_log.reset(q_token)
        llm.usage_log.reset(u_token)


class AskRequest(BaseModel):
    question: str
    graph_only: bool = False


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


@app.get("/api/resolve")
def resolve(q: str) -> dict:
    return {"query": q, "matches": brain.resolve_topic(q)}


@app.get("/api/experts")
def experts(
    topic: str | None = None, component: str | None = None, team: str | None = None, k: int = 8
) -> dict:
    return _with_queries(brain.experts, topic=topic, component=component, team=team, k=k)


@app.get("/api/reviewers")
def reviewers(pr: str, k: int = 3) -> dict:
    return _with_queries(brain.reviewers, pr, k=k)


@app.get("/api/onboarding")
def onboarding(component: str) -> dict:
    return _with_queries(brain.onboarding, component)


@app.get("/api/decisions/{decision_id}/trace")
def decision_trace(decision_id: str) -> dict:
    return _with_queries(brain.decision, decision_id)


@app.post("/api/ask")
def ask(req: AskRequest) -> dict:
    return _with_queries(agent.ask, req.question, graph_only=req.graph_only)
