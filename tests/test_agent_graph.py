"""The real LangGraph graph (CI installs langgraph; skipped where it is not installed)."""

import pytest

pytest.importorskip("langgraph")

from langgraph.checkpoint.memory import MemorySaver  # noqa: E402

from agent import graph as agent_graph  # noqa: E402
from agent import nodes  # noqa: E402
from agent.nodes import Deps  # noqa: E402
from agent.store import MemoryAgentStore  # noqa: E402
from intake.vault import MemoryVault  # noqa: E402


def test_graph_runs_end_to_end_and_resumes_after_a_crash(monkeypatch):
    store = MemoryAgentStore({"C-1001": {"tenant_id": "C-1001", "region": "IN"}})
    deps = Deps(store, MemoryVault(), b"k")
    tid = store.create("C-1001", "chat", "Payroll stuck at processing", None)
    real_draft, gate_calls = nodes.NODE_FUNCS["draft"], []
    real_gate = nodes.NODE_FUNCS["pii_gate"]

    def counting_gate(state, deps):
        gate_calls.append(1)
        return real_gate(state, deps)

    def crashing_draft(state, deps):
        raise MemoryError("killed")

    monkeypatch.setitem(nodes.NODE_FUNCS, "pii_gate", counting_gate)
    monkeypatch.setitem(nodes.NODE_FUNCS, "draft", crashing_draft)
    saver = MemorySaver()
    with pytest.raises(MemoryError):
        agent_graph.run(agent_graph.build(deps, saver), tid)
    monkeypatch.setitem(nodes.NODE_FUNCS, "draft", real_draft)
    state = agent_graph.run(agent_graph.build(deps, saver), tid)  # a new worker, same checkpoints
    assert state["sent"] and len(gate_calls) == 1
    again = agent_graph.run(agent_graph.build(deps, saver), tid)  # redelivered after completion
    assert again["sent"] and len(store.replies(tid)) == 1
