"""Vercel entrypoint: the FastAPI app (Vercel's Python runtime picks up `app` from main.py)."""

from moolai.api import app

__all__ = ["app"]
