"""Phase G API: console endpoints, lead vs admin tokens, feedback (runs where FastAPI is installed, e.g. CI)."""
import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

import api.main as main  # noqa: E402
from shared import settings  # noqa: E402
from tests.test_console import _mixed  # noqa: E402

client = TestClient(main.app)


@pytest.fixture
def console(monkeypatch):
    store, ids = _mixed()
    monkeypatch.setattr(main, "_store", store)
    monkeypatch.setattr(main, "_model", False)  # no model: translations say so, never guess
    monkeypatch.setattr(settings, "ADMIN_TOKEN", "admin-secret")
    monkeypatch.setattr(settings, "LEAD_TOKEN", "lead-secret")
    return store, ids


def test_console_needs_a_lead_or_admin_token(console):
    assert client.get("/console/summary").status_code == 401
    assert client.get("/console/summary", headers={"X-Admin-Token": "wrong"}).status_code == 401
    r = client.get("/console/summary", headers={"X-Admin-Token": "lead-secret"})
    assert r.status_code == 200 and r.json()["role"] == "lead"
    assert sum(b["n"] for b in r.json()["buckets"]) == r.json()["tickets"]


def test_lead_can_read_but_not_decide_reviews_or_import(console):
    lead = {"X-Admin-Token": "lead-secret"}
    assert client.get("/review/tasks", headers=lead).status_code == 401
    assert client.post("/knowledge", json={"articles": []}, headers=lead).status_code == 401


def test_queues_and_ticket_timeline(console):
    store, ids = console
    h = {"X-Admin-Token": "lead-secret"}
    r = client.get("/console/tickets?view=approval", headers=h).json()
    assert r["count"] == 2 and all(t["bucket"] == "approval" for t in r["tickets"])
    assert client.get("/console/tickets?view=nope", headers=h).status_code == 422
    t = client.get(f"/console/tickets/{ids[1]}", headers=h).json()
    assert t["bucket"] == "resolved" and t["decision"]["answer"]["sources"] and t["customer_saw"]


def test_customer_feedback(console):
    store, ids = console
    assert client.post(f"/tickets/{ids[1]}/feedback", json={"solved": False}).json()["feedback"] == "no"
    assert store.tickets[ids[1]]["feedback"] == "no"
    assert client.post("/tickets/not-a-uuid/feedback", json={"solved": True}).status_code == 404


def test_named_reviewer_decisions_are_attributed_from_the_token(console, monkeypatch):
    store, ids = console
    monkeypatch.setattr(settings, "REVIEWER_TOKENS", "priya:priya-token-123456789")
    h = {"X-Admin-Token": "priya-token-123456789"}
    tasks = client.get("/review/tasks", headers=h).json()
    task = next(t for t in tasks if t.get("kind", "reply") == "reply")
    r = client.post(f"/review/tasks/{task['id']}", headers=h, json={"decision": "approve", "reviewer": "someone else"})
    assert r.status_code == 200
    assert store.reviews[task["id"]]["assignee"] == "priya"
    assert client.post("/knowledge", json={"articles": []}, headers=h).status_code == 401  # reviewers cannot import


def test_compare_a_statutory_answer_on_another_date(console, monkeypatch):
    store, ids = console
    from tests.test_drafting import RULES

    monkeypatch.setattr(store, "rules", RULES, raising=False)
    h = {"X-Admin-Token": "lead-secret"}
    r = client.get(f"/console/tickets/{ids[2]}/compare?date=2026-07-15", headers=h)
    assert r.status_code == 200
    assert client.get(f"/console/tickets/{ids[2]}/compare?date=not-a-date", headers=h).status_code == 422
    t = client.get(f"/console/tickets/{ids[2]}", headers=h).json()
    assert t["role"] == "lead" and t["open_task"]
