"""Phase 5 gate, with the in-memory runner (same checkpoint semantics as LangGraph)."""

import threading

import pytest

from agent import keywords, nodes
from agent.nodes import Deps
from agent.runner import MemoryCheckpoints, run
from agent.store import MemoryAgentStore
from intake.vault import MemoryVault

TENANTS = {"C-1001": {"tenant_id": "C-1001", "region": "IN", "tier": "Enterprise"}}


def make():
    store = MemoryAgentStore(TENANTS)
    return store, Deps(store, MemoryVault(), b"k"), MemoryCheckpoints()


def test_one_ticket_goes_from_chat_to_a_reply():
    store, deps, cps = make()
    tid = store.create("C-1001", "chat", "How do I add a new employee? PAN ABCPK1234F", "Kavya Rao")
    state = run(tid, deps, cps)
    assert state["steps"] == [
        "pii_gate",
        "normalise",
        "resolve_tenant",
        "classify",
        "dedupe",
        "route",
        "draft",
        "output_guard",
        "send",
    ]
    assert state["sent"] and store.tickets[tid]["agent_status"] == "replied"
    reply = store.replies(tid)[0]["body"]
    assert "ABCPK1234F" not in state["body"] and "ABCPK1234F" not in reply
    assert tid not in store.inbox  # raw text gone after pii_gate


def test_crash_mid_run_resumes_from_the_failed_node_not_pii_gate(monkeypatch):
    store, deps, cps = make()
    tid = store.create("C-1001", "chat", "Salary not credited", None)
    calls = {"pii_gate": 0}
    real_gate, real_draft = nodes.NODE_FUNCS["pii_gate"], nodes.NODE_FUNCS["draft"]

    def counting_gate(state, deps):
        calls["pii_gate"] += 1
        return real_gate(state, deps)

    def crashing_draft(state, deps):
        raise MemoryError("worker killed")

    monkeypatch.setitem(nodes.NODE_FUNCS, "pii_gate", counting_gate)
    monkeypatch.setitem(nodes.NODE_FUNCS, "draft", crashing_draft)
    with pytest.raises(MemoryError):
        run(tid, deps, cps)
    assert cps.get(tid)["next"] == "draft"  # the checkpoint points at the failed node
    monkeypatch.setitem(nodes.NODE_FUNCS, "draft", real_draft)
    state = run(tid, deps, cps)  # SQS redelivers the message
    assert calls["pii_gate"] == 1  # not re-run
    assert state["steps"].count("pii_gate") == 1 and state["sent"]


def test_redelivered_message_after_completion_sends_nothing_twice():
    store, deps, cps = make()
    tid = store.create("C-1001", "chat", "Payslip download fails", None)
    run(tid, deps, cps)
    cps.saved.clear()  # even with the checkpoint lost
    again = run(tid, deps, cps)
    assert again["meta"]["sent_now"] is False  # the unique key refused the second send
    assert len(store.replies(tid)) == 1  # unique (ticket_id, draft_version)


def test_unknown_tenant_goes_to_the_queue_and_blocked_ticket_gets_a_holding_reply(monkeypatch):
    store, deps, cps = make()
    tid = store.create("C-9999", "chat", "hello", None)
    assert run(tid, deps, cps)["route"] == "queue"
    tid2 = store.create("C-1001", "chat", "hello", None)
    store.tickets[tid2]["status"] = "pii_blocked"
    store.tickets[tid2]["masked_body"] = None
    state = run(tid2, deps, cps)
    assert state["route"] == "block" and "specialist" in store.replies(tid2)[0]["body"]


def test_twenty_parallel_posts_create_one_ticket():
    store = MemoryAgentStore(TENANTS)
    ids, barrier = [], threading.Barrier(20)

    def post():
        barrier.wait()
        ids.append(store.create_idempotent("C-1001", "chat", "same message", idempotency_key="k-1"))

    threads = [threading.Thread(target=post) for _ in range(20)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len({i for i, _ in ids}) == 1 and sum(created for _, created in ids) == 1
    assert len(store.tickets) == 1


@pytest.mark.parametrize(
    "text,team",
    [
        ("WPS SIF file rejected by the bank", "Statutory"),
        ("Salary nahi aayi, payroll check karo", "Payroll"),
        ("لا أستطيع تسجيل الدخول، كلمة المرور لا تعمل", "Access / Login"),
        ("वेतन जमा नहीं हुआ", "Payroll"),
        ("Invoice for October is wrong", "Billing"),
    ],
)
def test_keyword_classifier_in_four_languages(text, team):
    assert keywords.classify(text)["team"] == team


def test_no_keywords_means_no_team():
    assert keywords.classify("hello there")["team"] is None
