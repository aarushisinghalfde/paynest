"""Phase 11 tracing: one span per graph node, plus a JSON timing event in the logs.

OpenTelemetry is used when it is installed and OTEL_EXPORTER_OTLP_ENDPOINT is set (for
example an ADOT collector that forwards to AWS X-Ray). Otherwise spans are no-ops and only
the `node_done` log event is written; CloudWatch metric filters already read those.
Span attributes are ids, route and timings only, never ticket text.
"""

import functools
import logging
import os
import time
from contextlib import contextmanager

from shared.logs import log_event, safe_error

log = logging.getLogger("trace")
_tracer = None


def tracer():
    global _tracer
    if _tracer is None:
        _tracer = False
        if os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
            try:
                from opentelemetry import trace
                from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
                from opentelemetry.sdk.resources import Resource
                from opentelemetry.sdk.trace import TracerProvider
                from opentelemetry.sdk.trace.export import BatchSpanProcessor

                provider = TracerProvider(resource=Resource.create({"service.name": "paynest-worker"}))
                provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
                trace.set_tracer_provider(provider)
                _tracer = trace.get_tracer("paynest.agent")
            except ImportError:
                log.info("OTEL endpoint set but opentelemetry is not installed; spans off")
    return _tracer or None


@contextmanager
def span(name: str, **attrs):
    t = tracer()
    if t is None:
        yield None
        return
    with t.start_as_current_span(name) as s:
        for k, v in attrs.items():
            if v is not None:
                s.set_attribute(k, v)
        yield s


def traced(node: str):
    def wrap(fn):
        @functools.wraps(fn)
        def inner(state, deps=None, **kw):
            t0 = time.perf_counter()
            ticket = state.get("ticket_id") if isinstance(state, dict) else None
            with span(f"node.{node}", ticket_id=ticket) as s:
                try:
                    out = fn(state, deps, **kw)
                except Exception as exc:
                    log_event(log, "node_failed", logging.ERROR, node=node, ticket_id=ticket, **safe_error(exc))
                    raise
                ms = round((time.perf_counter() - t0) * 1000, 1)
                if s is not None:
                    s.set_attribute("route", str(out.get("route") or state.get("route") or ""))
                    s.set_attribute("ms", ms)
                log_event(log, "node_done", node=node, ticket_id=ticket, ms=ms)
                return out

        return inner

    return wrap
