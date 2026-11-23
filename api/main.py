"""Payce Support Assist API.

Phase 1: liveness (/health) and readiness (/ready).
Phase 3: ticket intake. POST /tickets stores the ticket and queues its ID (the message
carries the ID only); the worker masks it before anything else reads it. GET
/tickets/{id} returns masked fields only, never the raw body.
Chat and review WebSockets arrive in phases 5 and 10.
"""

import json
import logging
import os
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
    conversation_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9-]{8,64}$")

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
    return {"status": "ok", "region": settings.REGION, "aws_region": settings.AWS_REGION,
            "version": os.environ.get("APP_VERSION", "dev")}


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
    if ticket.conversation_id:  # before queueing, so the agent sees it
        store.save_progress(ticket_id, conversation_id=ticket.conversation_id)
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


def _admin(token: str | None) -> str:
    """Admin only (knowledge import, settings). Returns "admin"."""
    if not settings.ADMIN_TOKEN:
        raise HTTPException(503, "review console disabled: ADMIN_TOKEN not set")
    import hmac

    if not token or not hmac.compare_digest(token, settings.ADMIN_TOKEN):
        raise HTTPException(401, "admin token required")
    return "admin"


def _reviewer(token: str | None) -> str:
    """Review queue: a named reviewer (REVIEWER_TOKENS) or the admin. Returns who is acting."""
    import hmac

    for t, name in settings.reviewers().items():
        if token and hmac.compare_digest(token, t):
            return name
    return _admin(token)


def _reader(token: str | None) -> str:
    """Phase G5: the console is read-only for the support lead (LEAD_TOKEN) and open to admins.
    Deciding reviews and importing knowledge stay admin-only. Returns the role."""
    import hmac

    if token and settings.ADMIN_TOKEN and hmac.compare_digest(token, settings.ADMIN_TOKEN):
        return "admin"
    if token and settings.LEAD_TOKEN and hmac.compare_digest(token, settings.LEAD_TOKEN):
        return "lead"
    if token and any(hmac.compare_digest(token, t) for t in settings.reviewers()):
        return "reviewer"
    if not settings.ADMIN_TOKEN and not settings.LEAD_TOKEN:
        raise HTTPException(503, "console disabled: ADMIN_TOKEN / LEAD_TOKEN not set")
    raise HTTPException(401, "lead or admin token required")


_model = None


def get_model():
    """The model client for translations (masked text only); None when no provider key is set."""
    global _model
    if _model is None:
        from agent.models import ModelClient, PgLedger

        client = ModelClient(ledger=PgLedger(settings.DATABASE_URL))
        _model = client if client.key else False
    return _model or None


# ---------------------------------------------------------------- support-head console (phase G)
VIEWS = ("all", "resolved", "approval", "approved", "human", "merged", "chat")


@app.get("/console/summary")
def console_summary(days: int = 7, x_admin_token: str | None = Header(default=None)) -> dict:
    """What the agent resolved itself, what went to a person and why, confidence, cache and RAG use."""
    role = _reader(x_admin_token)
    if not 1 <= days <= 90:
        raise HTTPException(422, "days 1-90")
    from agent import console

    store = get_store()
    return {**console.summarize(store.console_rows(days), store.model_cost(days)), "days": days, "role": role}


@app.get("/console/tickets")
def console_tickets(view: str = "all", days: int = 7, language: str | None = None, team: str | None = None,
                    x_admin_token: str | None = Header(default=None)) -> dict:
    _reader(x_admin_token)
    if view not in VIEWS or not 1 <= days <= 90:
        raise HTTPException(422, f"view one of {VIEWS}; days 1-90")
    from agent import console

    rows = console.queue_rows(get_store().console_rows(days), view, language, team)
    return {"view": view, "count": len(rows), "tickets": rows[:500]}


@app.get("/console/tickets/{ticket_id}")
def console_ticket(ticket_id: str, translate: bool = True, x_admin_token: str | None = Header(default=None)) -> dict:
    """One ticket's timeline: masked question, decision record, replies, reviews, and an English
    machine translation for Arabic/Hindi/Hinglish (made once, on first open, then stored)."""
    _reader(x_admin_token)
    try:
        uuid.UUID(ticket_id)
    except ValueError:
        raise HTTPException(404, "ticket not found") from None
    store = get_store()
    t = store.console_ticket(ticket_id)
    if t is None:
        raise HTTPException(404, "ticket not found")
    from agent import console
    from agent import translate as tr
    from agent.unmask import customer_view

    if translate and not t.get("translation") and t.get("language") in tr.NEEDS:
        t["translation"] = tr.for_ticket(t.get("masked_body") or "", [r["body"] for r in t["replies"]],
                                         t["language"], get_model(), ticket_id)
        if t["translation"]["question"].get("ok") or t["translation"]["reply"].get("ok"):
            store.save_progress(ticket_id, translation=t["translation"])
    t["bucket"] = console.bucket(t)
    t["customer_saw"] = [customer_view(r["body"]) for r in t["replies"]]
    return t


class Feedback(BaseModel):
    solved: bool


@app.post("/tickets/{ticket_id}/feedback")
def ticket_feedback(ticket_id: str, f: Feedback) -> dict:
    """The customer's "did this solve it?" from the chat (G4 trust signal)."""
    try:
        uuid.UUID(ticket_id)
    except ValueError:
        raise HTTPException(404, "ticket not found") from None
    if not get_store().set_feedback(ticket_id, "yes" if f.solved else "no"):
        raise HTTPException(404, "ticket not found")
    return {"ticket_id": ticket_id, "feedback": "yes" if f.solved else "no"}


@app.get("/dashboard")
def dashboard(scope: str = "live", days: int = 7, x_admin_token: str | None = Header(default=None)) -> dict:
    """Operations dashboard data (lead or admin token): classification, merges, resolution. Masked data only."""
    _reader(x_admin_token)
    if scope not in ("live", "export") or not 1 <= days <= 90:
        raise HTTPException(422, "scope must be live or export; days 1-90")
    from agent.dashboard import summarize

    return summarize(get_store().dashboard_data(scope, days), scope)


class ArticleFile(BaseModel):
    filename: str = Field(max_length=200)
    text: str = Field(max_length=60_000)


class KnowledgeUpload(BaseModel):
    articles: list[ArticleFile] = Field(default_factory=list, max_length=200)
    answers_csv: str | None = Field(default=None, max_length=500_000)
    imported_by: str | None = Field(default=None, max_length=80)


@app.get("/knowledge")
def knowledge_list(x_admin_token: str | None = Header(default=None)) -> dict:
    """Imported articles and the How-To answer library size (admin token)."""
    _admin(x_admin_token)
    return get_store().list_imports()


@app.post("/knowledge")
def knowledge_upload(up: KnowledgeUpload, x_admin_token: str | None = Header(default=None)) -> dict:
    """Import support articles and approved answers into the database (admin token).

    Everything is masked before it is stored; a file that fails validation stops the whole
    upload (nothing is half-imported). The agent picks the new knowledge up within a minute.
    """
    _admin(x_admin_token)
    from agent import knowledge_import as ki

    try:
        articles = [ki.parse_article(f.filename, f.text) for f in up.articles]
        answers = ki.parse_answers_csv(up.answers_csv) if up.answers_csv else []
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    store = get_store()
    result = {"articles": store.import_articles(articles, up.imported_by) if articles else [],
              "answers_imported": store.import_answers(answers, up.imported_by) if answers else 0,
              "answers_masked_values": sum(a["masked"] for a in answers)}
    log_event(log, "knowledge_imported", articles=len(articles), answers=len(answers))
    return result


@app.delete("/knowledge/{kb_id}")
def knowledge_withdraw(kb_id: str, x_admin_token: str | None = Header(default=None)) -> dict:
    _admin(x_admin_token)
    if not get_store().withdraw_article(kb_id.upper()):
        raise HTTPException(404, "no active import with that id")
    return {"withdrawn": kb_id.upper()}


@app.get("/review/tasks")
def review_tasks(x_admin_token: str | None = Header(default=None)) -> list:
    _reviewer(x_admin_token)
    return get_store().list_reviews()


@app.post("/review/tasks/{task_id}")
def review_decide(task_id: str, d: Decision, x_admin_token: str | None = Header(default=None)) -> dict:
    who = _reviewer(x_admin_token)
    # attribution comes from the token, never from the form; the shared admin token stays marked as such
    d.reviewer = who if who != "admin" else f"admin ({(d.reviewer or 'unnamed')[:40]})"
    try:
        ticket_id = get_store().decide_review(task_id, d.decision, d.body, d.reviewer)
    except ValueError as exc:  # a knowledge task approved without writing the answer
        raise HTTPException(400, str(exc)) from None
    if ticket_id is None:
        raise HTTPException(404, "task not found or already decided")
    log_event(log, "review_decided", task_id=task_id, ticket_id=ticket_id, decision=d.decision)
    return {"ticket_id": ticket_id, "decision": d.decision}
