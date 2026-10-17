"""Shared Claude client, request settings and a local cost ledger."""

import json
import time
from contextvars import ContextVar
from functools import cache

import anthropic

from .config import settings

# Server-side refusal fallback: if the model declines, the API reroutes by refusal category.
# Not accepted by the Batches API, so batch requests leave it out.
FALLBACK_BETA = "server-side-fallback-2026-07-01"

# USD per million tokens. Cache writes at the 5-minute TTL rate (1.25x input).
PRICES = {"claude-opus-5-5": {"input": 4.00, "output": 20.00, "cache_read": 0.20, "cache_write": 5.00}}

# Per-request log of model calls, returned by the API.
usage_log: ContextVar[list[dict] | None] = ContextVar("usage_log", default=None)


def available() -> bool:
    """True if a Claude credential is configured (otherwise /api/ask answers in graph-only mode)."""
    import os

    return bool(os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN"))


@cache
def client() -> anthropic.Anthropic:
    return anthropic.Anthropic()


def request_kwargs(effort: str) -> dict:
    """Model, effort and refusal fallback for live (non-batch) calls."""
    return {
        "model": settings.model,
        "output_config": {"effort": effort},
        "betas": [FALLBACK_BETA],
        "fallbacks": "default",
    }


def text_of(message) -> str:
    return "".join(block.text for block in message.content if block.type == "text").strip()


def cost_usd(model: str, usage, *, batch: bool = False) -> float:
    price = PRICES.get(model, PRICES["claude-opus-5-5"])
    total = (
        usage.input_tokens * price["input"]
        + usage.output_tokens * price["output"]
        + (getattr(usage, "cache_read_input_tokens", None) or 0) * price["cache_read"]
        + (getattr(usage, "cache_creation_input_tokens", None) or 0) * price["cache_write"]
    ) / 1_000_000
    return total / 2 if batch else total


def record_usage(label: str, message, *, batch: bool = False) -> dict:
    usage = message.usage
    entry = {
        "ts": int(time.time()),
        "label": label,
        "model": message.model,
        "input": usage.input_tokens,
        "output": usage.output_tokens,
        "cache_read": getattr(usage, "cache_read_input_tokens", None) or 0,
        "cost_usd": round(cost_usd(message.model, usage, batch=batch), 6),
    }
    log = usage_log.get()
    if log is not None:
        log.append(entry)
    if settings.usage_ledger:
        try:
            with open(settings.usage_ledger, "a", encoding="utf-8") as ledger:
                ledger.write(json.dumps(entry) + "\n")
        except OSError:
            pass
    return entry


def summarize(entries: list[dict]) -> dict:
    return {"calls": len(entries), "cost_usd": round(sum(e["cost_usd"] for e in entries), 4)}
