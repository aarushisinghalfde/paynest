"""Phase D: one trace per ticket - a `ticket` root span with every node as a child."""
from contextlib import contextmanager

from agent.nodes import Deps
from agent.runner import MemoryCheckpoints, run
from agent.store import MemoryAgentStore
from intake.vault import MemoryVault
from shared import tracing


class FakeTracer:
    def __init__(self):
        self.stack, self.spans = [], []

    @contextmanager
    def start_as_current_span(self, name):
        parent = self.stack[-1] if self.stack else None
        rec = {"name": name, "parent": parent, "attrs": {}}
        self.spans.append(rec)
        self.stack.append(name)

        class S:
            def set_attribute(self, k, v):
                rec["attrs"][k] = v

        try:
            yield S()
        finally:
            self.stack.pop()


def test_each_ticket_is_one_trace_with_the_nodes_as_children(monkeypatch):
    fake = FakeTracer()
    monkeypatch.setattr(tracing, "tracer", lambda: fake)
    store = MemoryAgentStore({"C-1001": {"tenant_id": "C-1001", "region": "IN"}})
    tid = store.create("C-1001", "chat", "hi", None)
    run(tid, Deps(store, MemoryVault(), b"k"), MemoryCheckpoints())
    root = fake.spans[0]
    assert root["name"] == "ticket" and root["parent"] is None and root["attrs"]["ticket_id"] == tid
    nodes = [s for s in fake.spans if s["name"].startswith("node.")]
    assert nodes and all(s["parent"] == "ticket" for s in nodes)
    assert all("hi" not in str(v) for s in fake.spans for v in s["attrs"].values())  # never ticket text


def test_tracing_is_off_without_an_endpoint(monkeypatch):
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    monkeypatch.setattr(tracing, "_tracer", None)
    assert tracing.tracer() is None
