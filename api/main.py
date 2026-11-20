"""Payce Support Assist API.

Phase 1: liveness (/health) and readiness (/ready).
Phase 3: ticket intake. POST /tickets stores the ticket and queues its ID (the message
carries the ID only); the worker masks it before anything else reads it. GET
/tickets/{id} returns masked fields only, never the raw body.
Chat and review WebSockets arrive in phases 5 and 10.
"""

import json
import logging
import re
import uuid

from fastapi import FastAPI, Header, HTTPException, Response
from pydantic import BaseModel, Field, field_validator

from shared import deps, settings
from shared.logs import log_event, safe_error

app = FastAPI(title="Payce Support Assist API", version="0.2.0")
log = logging.getLogger("api")

TENANT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{1,39}$")  # C-1001, check-phase3


class TicketIn(BaseModel):
    tenant_id: str
    body: str = Field(min_length=1, max_length=settings.MAX_TICKET_CHARS)
    channel: str = Field(default="web", pattern=r"^(web|email|chat)$")
    sender_name: str | None = Field(default=None, max_length=200)
    sender_email: str | None = Field(default=None, max_length=320)
    sender_phone: str | None = Field(default=None, max_length=40)

    @field_validator("tenant_id")
    @classmethod
    def _tenant(cls, v: str) -> str:
        if not TENANT_RE.match(v):
            raise ValueError("tenant_id: 2-40 letters, digits or hyphens")
        return v


# Swapped in tests; built lazily so importing the app needs no database or AWS.
_store = None
_queue = None


def get_store():
    global _store
    if _store is None:
        from agent.store import PgAgentStore

        _store = PgAgentStore(settings.DATABASE_URL)
    return _store


def get_queue():
    """Returns send(body: str). Real SQS (or ElasticMQ) by default."""
    global _queue
    if _queue is None:
        from shared.queue import queue_url, sqs_client

        client = sqs_client()
        url = queue_url(client)
        _queue = lambda body: client.send_message(QueueUrl=url, MessageBody=body)  # noqa: E731
    return _queue


@app.get("/health")
def health() -> dict:
    """Liveness: the process is up. Never touches other services."""
    return {"status": "ok", "region": settings.REGION, "aws_region": settings.AWS_REGION}


@app.get("/ready")
def ready(response: Response) -> dict:
    """Readiness: Postgres (with extensions), Redis and the queue are reachable."""
    checks = {}
    for name, check in deps.CHECKS.items():
        try:
            checks[name] = {"ok": True, "detail": check()}
        except Exception as exc:  # noqa: BLE001 - report every dependency
            checks[name] = {"ok": False, "detail": f"{type(exc).__name__}: {exc}"[:200]}
    ok = all(c["ok"] for c in checks.values())
    if not ok:
        response.status_code = 503
    return {"status": "ready" if ok else "not ready", "checks": checks}


@app.post("/tickets", status_code=202)
def create_ticket(
    ticket: TicketIn, response: Response, idempotency_key: str | None = Header(default=None, max_length=100)
) -> dict:
    """Store the ticket (raw text goes to the short-lived inbox only) and queue its ID.

    With an Idempotency-Key header, the same message posted again (a retry, a double click,
    20 parallel posts) returns the first ticket and is not queued twice.
    """
    store = get_store()
    ticket_id, created = store.create_idempotent(
        ticket.tenant_id,
        ticket.channel,
        ticket.body,
        ticket.sender_name,
        ticket.sender_email,
        ticket.sender_phone,
        idempotency_key,
    )
    if not created:
        response.status_code = 200
        return {"ticket_id": ticket_id, "status": "duplicate_request"}
    try:
        get_queue()(json.dumps({"ticket_id": ticket_id}))
    except Exception as exc:  # noqa: BLE001 - undo, so no ticket waits forever unqueued
        store.delete(ticket_id)
        log_event(log, "ticket_enqueue_failed", logging.ERROR, ticket_id=ticket_id, **safe_error(exc))
        raise HTTPException(503, "queue unavailable, ticket not accepted; please retry") from None
    log_event(
        log,
        "ticket_received",
        ticket_id=ticket_id,
        tenant_id=ticket.tenant_id,
        channel=ticket.channel,
        chars=len(ticket.body),
    )
    return {"ticket_id": ticket_id, "status": "received"}


@app.get("/tickets/{ticket_id}")
def get_ticket(ticket_id: str) -> dict:
    try:
        uuid.UUID(ticket_id)
    except ValueError:
        raise HTTPException(404, "ticket not found") from None
    ticket = get_store().get(ticket_id)
    if ticket is None:
        raise HTTPException(404, "ticket not found")
    if ticket["status"] != "masked":
        ticket["masked_body"] = None  # nothing to show until the gate has passed it
    from agent.unmask import customer_view

    ticket["replies"] = [{**r, "body": customer_view(r["body"])} for r in get_store().replies(ticket_id)]
    return ticket


# ---------------------------------------------------------------- reviewer console (minimal)
class Decision(BaseModel):
    decision: str = Field(pattern=r"^(approve|reject)$")
    body: str | None = Field(default=None, max_length=4000)
    reviewer: str = Field(default="reviewer", max_length=100)


def _admin(token: str | None):
    if not settings.ADMIN_TOKEN:
        raise HTTPException(503, "review console disabled: ADMIN_TOKEN not set")
    import hmac

    if not token or not hmac.compare_digest(token, settings.ADMIN_TOKEN):
        raise HTTPException(401, "admin token required")


@app.get("/review/tasks")
def review_tasks(x_admin_token: str | None = Header(default=None)) -> list:
    _admin(x_admin_token)
    return get_store().list_reviews()


@app.post("/review/tasks/{task_id}")
def review_decide(task_id: str, d: Decision, x_admin_token: str | None = Header(default=None)) -> dict:
    _admin(x_admin_token)
    ticket_id = get_store().decide_review(task_id, d.decision, d.body, d.reviewer)
    if ticket_id is None:
        raise HTTPException(404, "task not found or already decided")
    log_event(log, "review_decided", task_id=task_id, ticket_id=ticket_id, decision=d.decision)
    return {"ticket_id": ticket_id, "decision": d.decision}
