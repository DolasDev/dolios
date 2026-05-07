"""Pegasus tool stubs.

These will wrap a real Pegasus API client once one exists. For now the
functions raise NotImplementedError so the persona's tool allowlist has
something concrete to bind to. Names and signatures here MUST stay in sync
with personas/*.yaml until the persona loader can detect drift on its own.
"""
from __future__ import annotations

from typing import Any


def list_jobs(status: str | None = None) -> list[dict[str, Any]]:
    """List move jobs, optionally filtered by status."""
    raise NotImplementedError("Pegasus client not yet wired up")


def get_job(job_id: str) -> dict[str, Any]:
    """Fetch a single move job by id."""
    raise NotImplementedError("Pegasus client not yet wired up")


def create_estimate(customer_id: str, items: list[dict[str, Any]]) -> dict[str, Any]:
    """Create an estimate for a customer."""
    raise NotImplementedError("Pegasus client not yet wired up")
