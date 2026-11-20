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

from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel, Field, field_validator

from shared import deps, settings
from shared.logs import log_event, safe_error

app = FastAPI(title="Payce Support Assist API", version="0.2.0")
log = logging.getLogger("api")

TENANT_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,39}$")


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
            raise ValueError("tenant_id: 2-40 lowercase letters, digits or hyphens")
        return v


# Swapped in tests; built lazily so importing the app needs no database or AWS.
_store = None
_queue = None


def get_store():
    global _store
    if _store is None:
        from intake.store import PgTicketStore

        _store = PgTicketStore(settings.DATABASE_URL)
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
def create_ticket(ticket: TicketIn) -> dict:
    """Store the ticket (raw text goes to the short-lived inbox only) and queue its ID."""
    store = get_store()
    ticket_id = store.create(ticket.tenant_id, ticket.channel, ticket.body, ticket.sender_name,
                             ticket.sender_email, ticket.sender_phone)
    try:
        get_queue()(json.dumps({"ticket_id": ticket_id}))
    except Exception as exc:  # noqa: BLE001 - undo, so no ticket waits forever unqueued
        store.delete(ticket_id)
        log_event(log, "ticket_enqueue_failed", logging.ERROR, ticket_id=ticket_id, **safe_error(exc))
        raise HTTPException(503, "queue unavailable, ticket not accepted; please retry") from None
    log_event(log, "ticket_received", ticket_id=ticket_id, tenant_id=ticket.tenant_id,
              channel=ticket.channel, chars=len(ticket.body))
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
        ticket["masked_body"] = None      # nothing to show until the gate has passed it
    return ticket
