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

from agent import (
    answer_library,
    conversation,
    drafter,
    injection,
    keywords,
    retrieval,
    router,
    templates,
    tools,
)
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
    answer_cache: object = None  # agent.answer_cache (How-To answers): checked before RAG


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
                 "created_at": t.get("created_at") or datetime.now(UTC), "conversation_id": t.get("conversation_id")},
        "steps": _step(state, "pii_gate"),
    }


def _question(state) -> str:
    """The question to classify and answer: this message, plus the earlier one it follows up."""
    return " ".join(f"{state.get('context') or ''} {state.get('subject', '')} {state.get('body', '')}".split())


def normalise(state, deps: Deps):
    text = " ".join(f"{state.get('subject', '')} {state.get('body', '')}".split())
    talk = conversation.kind(text)
    history, context, status_of, context_team = [], None, None, None
    cid = state.get("meta", {}).get("conversation_id")
    if cid and hasattr(deps.store, "conversation"):
        history = [h for h in deps.store.conversation(cid, state["ticket_id"])
                   if h.get("tenant_id") in (None, state.get("tenant_id"))]  # same company only
        prev = history[-1] if history else None
        # joined with the previous turn only when it answers our clarifying question, or is plainly
        # a follow-up ("and for contractors?"); a new vague message gets its own clarifying question
        last = ((prev or {}).get("reply") or "")[-160:]
        # our last reply asked them something, and this is their answer (not a brand-new question)
        we_asked = ("?" in last or "؟" in last) and not conversation.is_new_question(text)
        if prev and talk not in ("greeting", "thanks") and prev.get("route") not in ("chat", None) and (
            prev.get("route") == "ask" or (we_asked and talk != "vague")
            or (talk is None and conversation.is_follow_up(text))
        ):
            context, context_team = prev["text"], prev.get("team")
            talk = None if talk == "vague" else talk
        elif prev and talk == "vague" and prev.get("route") in ("review", "queue", "incident"):
            talk = "status"  # "update?" while an earlier question is still with a person
            status_of = {"ref": prev["ticket_id"][:8], "route": prev.get("route")}
    return {"language": language(text), "injection_rules": injection.detect(text), "talk": talk,
            "context": context, "context_team": context_team, "status_of": status_of, "history": [{"text": h["text"][:400], "reply": (h.get("reply") or "")[:400]}
                                             for h in history[-3:]],
            "steps": _step(state, "normalise")}


def resolve_tenant(state, deps: Deps):
    return {"tenant": deps.store.tenant(state["tenant_id"]), "steps": _step(state, "resolve_tenant")}


def classify(state, deps: Deps):
    text = _question(state)
    if deps.classifier is None:  # phase 5 stand-in
        c = keywords.classify(text)
        c["branch"] = "auto" if c["team"] and c["confidence"] >= 0.5 else "triage"
    else:
        c = deps.classifier.classify(text, ticket_id=state["ticket_id"])
    continues_howto = state.get("context_team") == "How-To"  # the answer to our How-To question
    layers = c.get("layers") or {}
    # How-to phrasing is only a tie-breaker. On the Q3 data, forcing every "how do I ..." to How-To
    # cut accuracy from 95.9% to 86.3% (data migration -> Onboarding, PT slabs -> Statutory, ...).
    # It decides only when the classifier is unsure and How-To is tied for first in the keywords or
    # is the similar-tickets answer, or (no data loaded yet) when the keywords tie with How-To.
    scores = keywords.classify(text).get("scores") or {}
    howto_tied = bool(scores) and scores.get("How-To", 0) == max(scores.values())
    tie_break = conversation.is_howto(text) and (
        (deps.classifier is None and howto_tied)
        or (c.get("branch") != "auto" and (howto_tied or layers.get("similar") == "How-To")))
    if (tie_break or continues_howto) and not c.get("priority_signal") and not c.get("is_injection"):
        c = {**c, "second": c.get("team") if c.get("team") != "How-To" else c.get("second"), "team": "How-To",
             "branch": "auto", "confidence": max(float(c.get("confidence") or 0), 0.6),
             "source": f"{c.get('source', 'keywords')}+howto_phrase"}
    # "Status of payroll run PR-202609?" is a lookup in the payroll API, not a judgement call: when the
    # classifier is unsure (live check: Payroll vs Statutory too close -> queue), it is Payroll.
    if (c.get("branch") != "auto" and conversation.is_run_status(text)
            and not c.get("priority_signal") and not c.get("is_injection")):
        c = {**c, "second": c.get("team") if c.get("team") != "Payroll" else c.get("second"), "team": "Payroll",
             "branch": "auto", "confidence": max(float(c.get("confidence") or 0), 0.6),
             "source": f"{c.get('source', 'keywords')}+run_status"}
    # A statutory figure (PF ceiling, gratuity, TDS slab...) always goes to Statutory and so to review.
    # Eval: a Hindi PF-ceiling question read as Payroll and an Arabic gratuity question read as How-To,
    # and both were answered without a person (guide only, but still the wrong channel).
    if (c.get("team") != "Statutory" and conversation.asks_statutory_figure(text)
            and not c.get("is_injection")):
        c = {**c, "second": c.get("team"), "team": "Statutory", "branch": "auto",
             "confidence": max(float(c.get("confidence") or 0), 0.6),
             "source": f"{c.get('source', 'keywords')}+statutory_figure"}
    if state.get("talk") in ("greeting", "thanks", "status"):  # not a support topic: no team
        c = {**c, "team": None, "branch": "chat", "source": "conversation"}
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
    if state.get("talk") in ("greeting", "thanks", "vague") or conversation.is_howto(text):
        # a greeting or a how-to-use question is never an outage or a resubmit
        return {"duplicate_of": None, "steps": _step(state, "dedupe")}
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
        q = _question(state)
        as_of = retrieval.question_date(q, state.get("meta", {}).get("created_at"))
        region = (state.get("tenant") or {}).get("region")
        lang = state.get("language", "en")
        howto = route_ in ("reply", "queue") and (state.get("team") == "How-To" or conversation.is_howto(q))
        if howto:
            return {**out, "howto": True, **_howto(state, deps, q, region, lang, as_of, queued)}
        if route_ == "review":  # a person approves it: all approved sources and every tool
            hits = deps.retriever.search(q, region, as_of)
            facts = tools.run_tools(state, deps.retriever.rules, as_of, deps.payroll_url)
        else:  # sent without review: run status only, never a statutory figure
            hits = []
            facts = [] if queued else [f for f in tools.run_tools(state, deps.retriever.rules, as_of,
                                                                  deps.payroll_url) if f["tool"] != "get_rate"]
        d = drafter.draft(state, hits, facts, as_of, model=deps.model, rung=deps.draft_rung)
        sources = {"as_of": as_of.isoformat(), "hits": [{k: _iso(v) for k, v in h.items()} for h in hits],
                   "facts": facts}
        if d:
            fb = None
            if d["mode"] == "model" and route_ == "reply":  # sent without review: keep the fixed wording ready
                fb = drafter.fallback(hits, facts, as_of, ref, state.get("language", "en"))
            return {**out, "draft": d["reply"], "draft_mode": d["mode"], "citations": d["citations"],
                    "sources": sources, "fallback_draft": fb}
        out["sources"] = sources
    kind = {"block": "blocked", "incident": "incident", "duplicate": "duplicate", "ask": "clarify",
            "chat": {"thanks": "thanks", "status": "status"}.get(state.get("talk"), "greeting")}.get(route_, "ack")
    earlier = state.get("status_of") or {}
    text = templates.render(kind, state.get("language", "en"), ref=ref, team=state.get("team") or "support",
                            duplicate_of=state.get("duplicate_of") or "", earlier=earlier.get("ref", ""),
                            who="a payroll specialist" if earlier.get("route") == "review" else "our support team")
    return {**out, "draft": text, "draft_mode": "template"}


def _howto(state, deps: Deps, q, region, lang, as_of, queued) -> dict:
    """How-To agent: approved library -> answer cache -> RAG over guides (+ past resolutions) -> compose."""
    when = as_of.isoformat()
    # 1. approved answers written by support: real steps, reused for every similar question
    if hasattr(deps.store, "howto_answers"):
        hit = answer_library.best(q, deps.store.howto_answers(region, lang))
        if hit:
            src = answer_library.as_source(hit)
            return {"draft": f"{hit['answer']} [{src['chunk_id']}]", "draft_mode": "library",
                    "citations": [src["chunk_id"]],
                    "sources": {"as_of": when, "hits": [src], "facts": [], "library_similarity": hit["similarity"]}}
    # 2. answers already given (Redis), keyed by KB version
    if deps.answer_cache is not None:
        hit = deps.answer_cache.get(q, region, lang, deps.retriever.version)
        if hit:
            return {"draft": hit["answer"], "draft_mode": "cache", "citations": hit["citations"],
                    "sources": {"as_of": when, "hits": hit["hits"], "facts": [], "cache_similarity": hit["similarity"]}}
    # 3. RAG: guides ranked by title and by the past questions each one solved; run status if asked
    articles = deps.retriever.howto_articles(q, region, as_of)
    if state.get("context_team") == "How-To" and not any(a.get("has_steps") for a in articles):
        # second turn and still no written steps: a teammate takes over with the whole conversation
        learn = [a["kb_id"] or a["chunk_id"].split("#")[0] for a in articles[:1]] or ["none"]
        return {"sources": {"as_of": when, "hits": [], "facts": []}, **_template(state, "handoff"),
                "learn_kb": learn}
    facts = [] if queued else [f for f in tools.run_tools(state, deps.retriever.rules, as_of, deps.payroll_url)
                               if f["tool"] == "get_run_status"]
    sources = {"as_of": when, "hits": [{k: _iso(v) for k, v in a.items()} for a in articles], "facts": facts}
    # 4. compose a conversational reply from those sources only
    d = drafter.draft_howto(state, articles, model=deps.model, rung=deps.draft_rung)
    if d is None and facts:
        d = drafter.draft(state, [], facts, as_of, model=deps.model, rung=deps.draft_rung)
    if d is None:
        return {"sources": sources, **_template(state, "ack")}
    # 5. no source had real steps: ask support to write the answer once (learning loop, in send)
    learn = [a["kb_id"] or a["chunk_id"].split("#")[0] for a in articles[:1] if not a.get("has_steps")]
    fb = drafter.draft_howto(state, articles, model=None) if d["mode"] == "model" else None
    return {"draft": d["reply"], "draft_mode": d["mode"], "citations": d["citations"], "sources": sources,
            "learn_kb": learn, "fallback_draft": fb}


def _template(state, kind) -> dict:
    ref = state.get("meta", {}).get("ticket_ref") or state["ticket_id"][:8]
    text = templates.render(kind, state.get("language", "en"), ref=ref, team=state.get("team") or "support",
                            duplicate_of="", earlier="", who="our support team")
    return {"draft": text, "draft_mode": "template"}


def output_guard(state, deps: Deps):
    result = _guard(state, state.get("draft"))
    fb = state.get("fallback_draft")
    if not result.get("ok") and fb and fb.get("reply"):
        # How-To: the model's wording failed a check. The no-model draft uses the same sources and fixed
        # wording; if it passes, the customer gets that instead of waiting for a person.
        alt = _guard(state, fb["reply"])
        if alt.get("ok"):
            return {"guard": {**alt, "replaced": result.get("problems")}, "draft": fb["reply"],
                    "draft_mode": "fallback", "citations": fb["citations"], "steps": _step(state, "output_guard")}
    return {"guard": result, "steps": _step(state, "output_guard")}


def _guard(state, draft):
    src = state.get("sources") or {}
    as_of = src.get("as_of")
    return out_guard.check(
        draft,
        ticket_text=f"{state.get('subject', '')} {state.get('body', '')}",
        region=(state.get("tenant") or {}).get("region"),
        language=state.get("language", "en"),
        hits=src.get("hits"),
        facts=src.get("facts"),
        as_of=retrieval._as_date(as_of) if as_of else None,
        ref=state.get("meta", {}).get("ticket_ref") or state["ticket_id"][:8],
    )


def send(state, deps: Deps):
    common = dict(route=state.get("route"), route_reason=state.get("route_reason"),
                  classification=state.get("classification"), team=state.get("team"), language=state.get("language"),
                  route_rule=state.get("route_rule"), answer_tier=state.get("draft_mode"))
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
    tier = {"cache": "the How-To cache", "library": "approved How-To answers"}.get(state.get("draft_mode"))
    if tier:
        common["route_reason"] = f"{common.get('route_reason') or ''} (answered from {tier})".strip()
    sent_now = deps.store.insert_reply(state["ticket_id"], state["draft_version"], state["draft"], "chat")
    deps.store.save_progress(state["ticket_id"], agent_status="replied", **common)
    _cache_answer(state, deps)
    _ask_support_to_write_it(state, deps)
    return {"sent": True, "meta": {**state.get("meta", {}), "sent_now": sent_now}, "steps": _step(state, "send")}


def _ask_support_to_write_it(state, deps: Deps):
    """Learning loop: the customer got a guide, not steps. Support writes the answer once; on approval the
    customer gets it and it joins the library for every future asker. One open task per question."""
    if not state.get("learn_kb") or not hasattr(deps.store, "create_review"):
        return
    q = _question(state)
    for t in deps.store.list_reviews():
        if t.get("kind") == "knowledge" and answer_library.similarity(q, t.get("body") or "") >= 0.75:
            return
    deps.store.create_review(
        state["ticket_id"], state["draft_version"] + 1, "",
        f"How-To knowledge: write the steps once (guide {state['learn_kb'][0]}); the customer gets them and every "
        f"similar question is answered automatically from then on", kind="knowledge", kb_ids=state["learn_kb"])


def _cache_answer(state, deps: Deps):
    """3. A How-To answer that passed the guard and was sent is kept for the next asker."""
    if (deps.answer_cache is None or deps.retriever is None or not state.get("howto")
            or state.get("draft_mode") not in ("model", "fallback")):
        return
    src = state.get("sources") or {}
    deps.answer_cache.put(_question(state), (state.get("tenant") or {}).get("region"), state.get("language", "en"),
                          deps.retriever.version, state["draft"], state.get("citations") or [], src.get("hits") or [])


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
