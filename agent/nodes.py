"""The graph's nodes. Each takes the state and returns only the fields it changes.

Phase 5 stand-ins (marked): classify is keyword-only, route has one rule, draft is a
fixed template, output_guard checks the schema only. pii_gate, normalise and
resolve_tenant are real. Every node is idempotent, so re-running one after a crash is safe.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from agent import dedupe as dd
from agent import injection, keywords, router, templates
from intake.pipeline import process_ticket
from loader.normalize import language


@dataclass
class Deps:
    store: object
    vault: object
    hmac_key: bytes
    ttl_days: int = 30
    classifier: object = None  # agent.classifier.Classifier (phase 6); keywords only when None


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
    return {"language": language(text), "injection_rules": injection.detect(text), "steps": _step(state, "normalise")}


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


def draft(state, deps: Deps):  # phase 5-7: templates per route; phase 8 drafts from sources
    ref = state.get("meta", {}).get("ticket_ref") or state["ticket_id"][:8]
    kind = {"block": "blocked", "incident": "incident", "duplicate": "duplicate"}.get(state.get("route"), "ack")
    text = templates.render(kind, state.get("language", "en"), ref=ref, team=state.get("team") or "support",
                            duplicate_of=state.get("duplicate_of") or "")
    return {"draft": text, "draft_version": state.get("draft_version", 0) + 1, "steps": _step(state, "draft")}


def output_guard(state, deps: Deps):  # phase 5 stand-in: schema only
    d = state.get("draft")
    problems = []
    if not isinstance(d, str) or not d.strip():
        problems.append("empty draft")
    elif len(d) > 4000:
        problems.append("draft too long")
    return {"guard": {"ok": not problems, "problems": problems}, "steps": _step(state, "output_guard")}


def send(state, deps: Deps):
    if not state.get("guard", {}).get("ok"):
        deps.store.save_progress(state["ticket_id"], agent_status="failed", route_reason="output guard failed")
        return {"sent": False, "steps": _step(state, "send")}
    common = dict(route=state.get("route"), route_reason=state.get("route_reason"),
                  classification=state.get("classification"), team=state.get("team"), language=state.get("language"))
    if state.get("route") == "review" and hasattr(deps.store, "create_review"):
        # a human approves before anything is sent (statutory, P1, known issue)
        deps.store.create_review(state["ticket_id"], state["draft_version"], state["draft"], state.get("route_reason"))
        deps.store.save_progress(state["ticket_id"], agent_status="waiting_review", **common)
        return {"sent": False, "waiting_review": True, "steps": _step(state, "send")}
    sent_now = deps.store.insert_reply(state["ticket_id"], state["draft_version"], state["draft"], "chat")
    deps.store.save_progress(state["ticket_id"], agent_status="replied", **common)
    return {"sent": True, "meta": {**state.get("meta", {}), "sent_now": sent_now}, "steps": _step(state, "send")}


NODE_FUNCS = {
    "pii_gate": pii_gate,
    "normalise": normalise,
    "resolve_tenant": resolve_tenant,
    "classify": classify,
    "dedupe": dedupe,
    "route": route,
    "draft": draft,
    "output_guard": output_guard,
    "send": send,
}
