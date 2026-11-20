"""The graph's nodes. Each takes the state and returns only the fields it changes.

draft (phase 8) writes from retrieved sources and tool facts when a retriever is set, for
the reply and review routes (review: a person approves it first), and offers a matching
guide on queued tickets; it falls back to the acknowledgement when the sources do not
answer the question; other routes, or no retriever, get the fixed templates.
output_guard (phase 9) runs agent.guard on every draft; a failed draft is never sent, it
goes to a reviewer with the problems. Every node is idempotent, so re-running one after a
crash is safe. Every node is traced (shared/tracing.py, phase 11).
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from agent import conversation, drafter, injection, keywords, retrieval, router, templates, tools
from agent import dedupe as dd
from agent import guard as out_guard
from intake.pipeline import process_ticket
from loader.normalize import language
from shared.tracing import traced


@dataclass
class Deps:
    store: object
    vault: object
    hmac_key: bytes
    ttl_days: int = 30
    classifier: object = None  # agent.classifier.Classifier (phase 6); keywords only when None
    retriever: object = None  # agent.retrieval.Retriever (phase 8); templates only when None
    model: object = None  # agent.models.ModelClient for drafting; the cited fallback when None
    payroll_url: str | None = None  # payroll API for get_run_status
    draft_rung: int = 1


def _step(state, name):
    return [*state.get("steps", []), name]


def pii_gate(state, deps: Deps):
    t = deps.store.masked(state["ticket_id"])
    if t and t["status"] == "received":
        process_ticket(state["ticket_id"], deps.store, deps.vault, deps.hmac_key, deps.ttl_days)
        t = deps.store.masked(state["ticket_id"])
    if t is None:
        raise LookupError("ticket not found")
    blocked = t["status"] == "pii_blocked"
    return {
        "tenant_id": t["tenant_id"],
        "subject": t["subject"] or "",
        "body": t["body"] or "",
        "route": "block" if blocked else state.get("route"),
        "route_reason": "pii re-scan quarantined the ticket" if blocked else state.get("route_reason"),
        "meta": {**state.get("meta", {}), "ticket_ref": t.get("ticket_ref"),
                 "created_at": t.get("created_at") or datetime.now(UTC)},
        "steps": _step(state, "pii_gate"),
    }


def normalise(state, deps: Deps):
    text = " ".join(f"{state.get('subject', '')} {state.get('body', '')}".split())
    return {"language": language(text), "injection_rules": injection.detect(text), "talk": conversation.kind(text),
            "steps": _step(state, "normalise")}


def resolve_tenant(state, deps: Deps):
    return {"tenant": deps.store.tenant(state["tenant_id"]), "steps": _step(state, "resolve_tenant")}


def classify(state, deps: Deps):
    text = f"{state.get('subject', '')} {state.get('body', '')}"
    if deps.classifier is None:  # phase 5 stand-in
        c = keywords.classify(text)
        c["branch"] = "auto" if c["team"] and c["confidence"] >= 0.6 else "triage"
    else:
        c = deps.classifier.classify(text, ticket_id=state["ticket_id"])
    return {
        "team": c["team"],
        "confidence": c["confidence"],
        "classification": c,
        "steps": _step(state, "classify"),
    }


def dedupe(state, deps: Deps):
    """Duplicate of a recent ticket? Part of a burst (incident)? A known Jira issue?"""
    if state.get("route") == "block" or not hasattr(deps.store, "recent_tickets"):
        return {"duplicate_of": None, "steps": _step(state, "dedupe")}
    text = f"{state.get('subject', '')} {state.get('body', '')}"
    created = state.get("meta", {}).get("created_at")
    recent = deps.store.recent_tickets(state["tenant_id"], created, state["ticket_id"])
    dup, why = dd.find_duplicate(text, created, recent)
    out = {"duplicate_of": dup, "duplicate_reason": why}
    if not dup:
        inc = dd.find_incident(text, created, recent, deps.store.open_incidents(state["tenant_id"]))
        if inc.get("opened"):
            deps.store.open_incident(inc["incident_id"], state["tenant_id"], state.get("team"), inc["signature"],
                                     created, [*inc["members"], state["ticket_id"]])
        if inc:
            out |= {"incident_id": inc["incident_id"], "incident_size": len(inc["members"]) + 1}
            deps.store.attach_incident(state["ticket_id"], inc["incident_id"])
        out["jira_key"] = dd.match_jira(text, deps.store.open_jira(state["tenant_id"]))
    deps.store.save_progress(state["ticket_id"], duplicate_of_ref=dup, jira_key=out.get("jira_key"))
    return {**out, "steps": _step(state, "dedupe")}


def route(state, deps: Deps):
    d = router.decide(router.facts_from_state(state))
    return {"route": d["route"], "route_reason": d["reason"], "route_rule": d["rule"], "queue": d.get("queue"),
            "steps": _step(state, "route")}


def _iso(v):
    return v.isoformat() if hasattr(v, "isoformat") else v


def draft(state, deps: Deps):
    ref = state.get("meta", {}).get("ticket_ref") or state["ticket_id"][:8]
    route_ = state.get("route")
    out = {"draft_version": state.get("draft_version", 0) + 1, "steps": _step(state, "draft")}
    queued = route_ == "queue" and state.get("tenant") is not None  # triage/pod queue, known tenant
    if deps.retriever is not None and (route_ in ("reply", "review") or queued):
        q = f"{state.get('subject', '')} {state.get('body', '')}"
        as_of = retrieval.question_date(q, state.get("meta", {}).get("created_at"))
        region = (state.get("tenant") or {}).get("region")
        if queued:  # a team picks it up; meanwhile offer a matching guide, never a statutory figure
            hits, facts = deps.retriever.search(q, region, as_of, kinds=("kb_title",)), []
        else:
            hits = deps.retriever.search(q, region, as_of)
            facts = tools.run_tools(state, deps.retriever.rules, as_of, deps.payroll_url)
        d = drafter.draft(state, hits, facts, as_of, model=deps.model, rung=deps.draft_rung)
        sources = {"as_of": as_of.isoformat(), "hits": [{k: _iso(v) for k, v in h.items()} for h in hits],
                   "facts": facts}
        if d:
            return {**out, "draft": d["reply"], "draft_mode": d["mode"], "citations": d["citations"],
                    "sources": sources}
        out["sources"] = sources
    kind = {"block": "blocked", "incident": "incident", "duplicate": "duplicate", "ask": "clarify",
            "chat": "thanks" if state.get("talk") == "thanks" else "greeting"}.get(route_, "ack")
    text = templates.render(kind, state.get("language", "en"), ref=ref, team=state.get("team") or "support",
                            duplicate_of=state.get("duplicate_of") or "")
    return {**out, "draft": text, "draft_mode": "template"}


def output_guard(state, deps: Deps):
    src = state.get("sources") or {}
    as_of = src.get("as_of")
    result = out_guard.check(
        state.get("draft"),
        ticket_text=f"{state.get('subject', '')} {state.get('body', '')}",
        region=(state.get("tenant") or {}).get("region"),
        language=state.get("language", "en"),
        hits=src.get("hits"),
        facts=src.get("facts"),
        as_of=retrieval._as_date(as_of) if as_of else None,
        ref=state.get("meta", {}).get("ticket_ref") or state["ticket_id"][:8],
    )
    return {"guard": result, "steps": _step(state, "output_guard")}


def send(state, deps: Deps):
    common = dict(route=state.get("route"), route_reason=state.get("route_reason"),
                  classification=state.get("classification"), team=state.get("team"), language=state.get("language"))
    g = state.get("guard", {})
    if not g.get("ok"):
        reason = "output guard: " + ", ".join(g.get("problems") or ["failed"])
        if hasattr(deps.store, "create_review") and state.get("draft"):
            # never sent: a person sees the draft and the problems, and fixes or rejects it
            deps.store.create_review(state["ticket_id"], state["draft_version"], state["draft"], reason)
            deps.store.save_progress(state["ticket_id"], agent_status="waiting_review", **{**common, "route_reason": reason})
            return {"sent": False, "waiting_review": True, "steps": _step(state, "send")}
        deps.store.save_progress(state["ticket_id"], agent_status="failed", route_reason=reason)
        return {"sent": False, "steps": _step(state, "send")}
    if state.get("route") == "review" and hasattr(deps.store, "create_review"):
        # a human approves before anything is sent (statutory, P1, known issue)
        deps.store.create_review(state["ticket_id"], state["draft_version"], state["draft"], state.get("route_reason"))
        deps.store.save_progress(state["ticket_id"], agent_status="waiting_review", **common)
        return {"sent": False, "waiting_review": True, "steps": _step(state, "send")}
    sent_now = deps.store.insert_reply(state["ticket_id"], state["draft_version"], state["draft"], "chat")
    deps.store.save_progress(state["ticket_id"], agent_status="replied", **common)
    return {"sent": True, "meta": {**state.get("meta", {}), "sent_now": sent_now}, "steps": _step(state, "send")}


NODE_FUNCS = {
    name: traced(name)(fn)
    for name, fn in {
        "pii_gate": pii_gate,
        "normalise": normalise,
        "resolve_tenant": resolve_tenant,
        "classify": classify,
        "dedupe": dedupe,
        "route": route,
        "draft": draft,
        "output_guard": output_guard,
        "send": send,
    }.items()
}
