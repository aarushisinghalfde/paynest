"""The graph's nodes. Each takes the state and returns only the fields it changes.

Phase 5 stand-ins (marked): classify is keyword-only, route has one rule, draft is a
fixed template, output_guard checks the schema only. pii_gate, normalise and
resolve_tenant are real. Every node is idempotent, so re-running one after a crash is safe.
"""

from dataclasses import dataclass

from agent import keywords, templates
from intake.pipeline import process_ticket
from loader.normalize import language


@dataclass
class Deps:
    store: object
    vault: object
    hmac_key: bytes
    ttl_days: int = 30


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
        "meta": {**state.get("meta", {}), "ticket_ref": t.get("ticket_ref")},
        "steps": _step(state, "pii_gate"),
    }


def normalise(state, deps: Deps):
    text = " ".join(f"{state.get('subject', '')} {state.get('body', '')}".split())
    return {"language": language(text), "steps": _step(state, "normalise")}


def resolve_tenant(state, deps: Deps):
    return {"tenant": deps.store.tenant(state["tenant_id"]), "steps": _step(state, "resolve_tenant")}


def classify(state, deps: Deps):  # phase 5 stand-in: keywords only
    c = keywords.classify(f"{state.get('subject', '')} {state.get('body', '')}")
    return {
        "team": c["team"],
        "confidence": c["confidence"],
        "classification": c,
        "steps": _step(state, "classify"),
    }


def dedupe(state, deps: Deps):  # phase 7
    return {"duplicate_of": None, "steps": _step(state, "dedupe")}


def route(state, deps: Deps):  # phase 5 stand-in: one rule
    if state.get("route") == "block":
        return {"steps": _step(state, "route")}
    if state.get("tenant") is None:
        return {
            "route": "queue",
            "route_reason": "unknown tenant: triage desk",
            "steps": _step(state, "route"),
        }
    return {
        "route": "reply",
        "route_reason": f"acknowledge; owner team {state.get('team') or 'triage'}",
        "steps": _step(state, "route"),
    }


def draft(state, deps: Deps):  # phase 5 stand-in: a fixed template
    ref = state.get("meta", {}).get("ticket_ref") or state["ticket_id"][:8]
    kind = "blocked" if state.get("route") == "block" else "ack"
    text = templates.render(kind, state.get("language", "en"), ref=ref, team=state.get("team") or "support")
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
        deps.store.save_progress(
            state["ticket_id"], agent_status="failed", route_reason="output guard failed"
        )
        return {"sent": False, "steps": _step(state, "send")}
    sent_now = deps.store.insert_reply(state["ticket_id"], state["draft_version"], state["draft"], "chat")
    deps.store.save_progress(
        state["ticket_id"],
        agent_status="replied",
        route=state.get("route"),
        route_reason=state.get("route_reason"),
        classification=state.get("classification"),
        team=state.get("team"),
        language=state.get("language"),
    )
    return {
        "sent": True,
        "meta": {**state.get("meta", {}), "sent_now": sent_now},
        "steps": _step(state, "send"),
    }


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
