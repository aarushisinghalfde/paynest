"""Ticket intake endpoints with an in-memory store and queue."""
import json

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

import api.main as api_main  # noqa: E402
from agent.store import MemoryAgentStore  # noqa: E402

client = TestClient(api_main.app)


@pytest.fixture
def wired(monkeypatch):
    store, sent = MemoryAgentStore(), []
    monkeypatch.setattr(api_main, "_store", store)
    monkeypatch.setattr(api_main, "_queue", sent.append)
    return store, sent


def test_post_stores_and_queues_the_id_only(wired):
    store, sent = wired
    resp = client.post("/tickets", json={"tenant_id": "acme-in", "body": "PAN ABCPK1234F wrong",
                                         "sender_email": "a@b.com"})
    assert resp.status_code == 202
    tid = resp.json()["ticket_id"]
    assert json.loads(sent[0]) == {"ticket_id": tid}          # the message carries no ticket text
    assert store.inbox[tid].body == "PAN ABCPK1234F wrong"


def test_get_hides_body_until_masked(wired):
    store, _ = wired
    tid = client.post("/tickets", json={"tenant_id": "acme-in", "body": "hello"}).json()["ticket_id"]
    got = client.get(f"/tickets/{tid}").json()
    assert got["status"] == "received" and got["masked_body"] is None
    assert "hello" not in json.dumps(got)
    store.save_masked(tid, "hello <NAME_1>", {"NAME": 1}, None, None, "rules")
    assert client.get(f"/tickets/{tid}").json()["masked_body"] == "hello <NAME_1>"


def test_queue_failure_rolls_back(wired, monkeypatch):
    store, _ = wired

    def down(_):
        raise ConnectionError("sqs down")

    monkeypatch.setattr(api_main, "_queue", down)
    resp = client.post("/tickets", json={"tenant_id": "acme-in", "body": "x"})
    assert resp.status_code == 503 and store.tickets == {} and store.inbox == {}


@pytest.mark.parametrize("payload", [
    {"tenant_id": "a b", "body": "x"},
    {"tenant_id": "acme-in", "body": ""},
    {"tenant_id": "acme-in", "body": "x" * 20001},
    {"tenant_id": "acme-in", "body": "x", "channel": "fax"},
])
def test_invalid_ticket_rejected(wired, payload):
    assert client.post("/tickets", json=payload).status_code == 422


def test_unknown_or_bad_id_is_404(wired):
    assert client.get("/tickets/not-a-uuid").status_code == 404
    assert client.get("/tickets/00000000-0000-0000-0000-000000000000").status_code == 404


def test_same_idempotency_key_creates_one_ticket_and_queues_once(wired):
    store, sent = wired
    h = {"Idempotency-Key": "msg-42"}
    first = client.post("/tickets", json={"tenant_id": "C-1001", "body": "help"}, headers=h)
    again = client.post("/tickets", json={"tenant_id": "C-1001", "body": "help"}, headers=h)
    assert first.status_code == 202 and again.status_code == 200
    assert again.json()["ticket_id"] == first.json()["ticket_id"]
    assert len(store.tickets) == 1 and len(sent) == 1


def test_get_shows_replies(wired):
    store, _ = wired
    tid = client.post("/tickets", json={"tenant_id": "C-1001", "body": "hello"}).json()["ticket_id"]
    store.insert_reply(tid, 1, "Thanks, ticket received.", "chat")
    assert client.get(f"/tickets/{tid}").json()["replies"][0]["body"] == "Thanks, ticket received."
