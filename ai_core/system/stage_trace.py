"""Opt-in stage recorder for the production retrieval-to-prompt path.

Production code calls ``emit`` at each stage; outside ``tracing()`` it does nothing, so the traced functions are the
very ones that serve users (tools/trace_evidence.py reads what they report; it never re-implements a stage).
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar

_events: ContextVar[list | None] = ContextVar('ocop_trace_events', default=None)


@contextmanager
def tracing():
    events: list[dict] = []
    token = _events.set(events)
    try:
        yield events
    finally:
        _events.reset(token)


def active() -> bool:
    return _events.get() is not None


def emit(stage: str, **payload) -> None:
    events = _events.get()
    if events is not None:
        events.append({'stage': stage, **payload})
