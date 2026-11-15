"""Optional low-cardinality OpenTelemetry instrumentation.

No user query, dossier contents, PDF text, secrets or raw prompts are recorded.
Without the optional opentelemetry package this is a no-op (not fake tracing).
"""

from __future__ import annotations
from contextlib import contextmanager
from functools import wraps
from time import monotonic

try:
    from opentelemetry import trace
except ImportError:
    trace = None


def available() -> bool:
    return trace is not None


@contextmanager
def observe(operation: str, **attrs):
    if trace is None:
        yield None
        return
    tracer = trace.get_tracer("ocop-graphrag")
    start = monotonic()
    with tracer.start_as_current_span(operation) as span:
        for name, value in attrs.items():
            if value is not None and isinstance(value, (str, int, float, bool)):
                span.set_attribute("ocop." + name, value)
        try:
            yield span
        except BaseException as exc:
            span.record_exception(exc)
            span.set_attribute("ocop.failed", True)
            raise
        finally:
            span.set_attribute("ocop.latency_ms", round((monotonic() - start) * 1000, 2))


def traced(operation: str):
    def decorate(func):
        @wraps(func)
        def wrapped(*args, **kwargs):
            with observe(operation):
                return func(*args, **kwargs)

        return wrapped

    return decorate
