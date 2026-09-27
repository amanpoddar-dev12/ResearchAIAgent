"""Convenience entrypoint: uvicorn server:app --reload."""

from server.main import app

__all__ = ["app"]
