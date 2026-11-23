"""Phase G3: the support-head console - one bucket per ticket, the overview numbers, queue rows.

Every live ticket lands in exactly ONE bucket, so the overview always adds up to the ticket count
(the console gate checks that):

  resolved   the agent answered on its own: sent an answer from the library, the cache or the
             sources (RAG / facts), no person involved. An acknowledgement template is NOT a
             resolution: R99 "acknowledged, owner queue Payroll" means a team still has to act.
  approval   a draft waits for a person (statutory, P1, known issue, or a failed guard)
  approved   a person approved the agent's draft (as is or edited), then it was sent
  human      a person owns it: acknowledged and queued to a team, blocked (injection), rejected
             draft, taken over
  merged     part of an incident or a duplicate of an earlier ticket
  chat       greetings, thanks, status questions and "tell me more" (no support work)

Masked text and ids only; translations are English renderings of masked text.
"""

from collections import Counter
from statistics import median

BUCKETS = ("resolved", "approval", "approved", "human", "merged", "chat")
LABEL = {"resolved": "Resolved by the agent", "approval": "Waiting for approval", "approved": "Approved by a person",
         "human": "With a person", "merged": "Merged (incident / duplicate)", "chat": "Conversation only"}
ANSWER_TIERS = {"library", "cache", "model", "fallback"}  # a real answer, not an acknowledgement
BANDS = ((0.9, "0.9-1.0"), (0.7, "0.7-0.9"), (0.5, "0.5-0.7"), (0.0, "below 0.5"))


def bucket(t: dict) -> str:
    route, status, outcome = t.get("route"), t.get("agent_status"), t.get("review_outcome")
    if route in ("incident", "duplicate"):
        return "merged"
    if route in ("chat", "ask"):
        return "chat"
    if status == "waiting_review":
        return "approval"
    if outcome in ("approved_as_is", "edited") and status == "replied":
        return "approved"
    tier = (t.get("decision") or {}).get("answer", {}).get("tier") or t.get("answer_tier")
    if route == "reply" and status == "replied" and tier in ANSWER_TIERS:
        return "resolved"
    return "human"  # queue, block, rejected, taken over, failed, still in progress


def _band(conf) -> str | None:
    if conf is None:
        return None
    return next(label for low, label in BANDS if conf >= low)


def _conf(t):
    c = (t.get("decision") or {}).get("classification", {}).get("confidence")
    if c is None:
        c = (t.get("classification") or {}).get("confidence") if isinstance(t.get("classification"), dict) else None
    try:
        return float(c)
    except (TypeError, ValueError):
        return None


def summarize(rows: list[dict], cost_usd: float = 0.0, baseline: dict | None = None) -> dict:
    by = Counter(bucket(t) for t in rows)
    work = len(rows) - by["chat"]  # tickets that needed support work
    dec = [t.get("decision") or {} for t in rows]
    answers = [d.get("answer") or {} for d in dec]
    tiers = Counter(a.get("tier") for a in answers if a.get("tier"))
    howto = [t for t in rows if t.get("team") == "How-To" and bucket(t) != "chat"]
    howto_tiers = Counter((t.get("decision") or {}).get("answer", {}).get("tier") for t in howto)
    guards = [d.get("guard") or {} for d in dec if d.get("guard")]
    failed = Counter(p for g in guards for p in g.get("failed") or [])
    cache_sims = [a["cache_similarity"] for a in answers if a.get("cache_similarity") is not None]
    top_rag = [a["sources"][0]["score"] for a in answers if a.get("tier") in ("model", "fallback") and a.get("sources")
               and a["sources"][0].get("score") is not None]

    bands = {}
    for t in rows:
        b = _band(_conf(t))
        if b is None or bucket(t) == "chat":
            continue
        x = bands.setdefault(b, {"band": b, "tickets": 0, "resolved": 0, "reviewed": 0, "approved_as_is": 0,
                                 "edited": 0, "rejected": 0, "said_not_solved": 0})
        x["tickets"] += 1
        x["resolved"] += bucket(t) == "resolved"
        o = t.get("review_outcome")
        if o in ("approved_as_is", "edited", "rejected"):
            x["reviewed"] += 1
            x[o] += 1
        x["said_not_solved"] += t.get("feedback") == "no"

    reviewed = [t for t in rows if t.get("review_outcome") in ("approved_as_is", "edited", "rejected")]
    minutes = [t["review_minutes"] for t in reviewed if t.get("review_minutes") is not None]
    confs = [c for c in (_conf(t) for t in rows if bucket(t) != "chat") if c is not None]
    answered = [t for t in rows if bucket(t) in ("resolved", "approved")]
    backed = [t for t in answered if ((t.get("decision") or {}).get("answer") or {}).get("citations")]
    first = [t["first_reply_seconds"] for t in rows if t.get("first_reply_seconds") is not None and bucket(t) == "resolved"]
    agent_ms = [sum((t.get("decision") or {}).get("timings_ms", {}).values()) for t in rows
                if (t.get("decision") or {}).get("timings_ms")]
    costs = [t.get("cost_usd") or 0.0 for t in rows]
    impact = {
        "median_seconds_to_answer": round(median(first), 1) if first else None,
        "median_agent_ms": round(median(agent_ms)) if agent_ms else None,
        "cost_per_support_ticket": round(sum(costs) / work, 5) if work else None,
        "answers_backed_by_a_source": round(len(backed) / len(answered), 3) if answered else None,
        "out_of_date_rule_stopped": failed["superseded_source"],
        "statutory_sent_without_a_person": sum(1 for t in rows if t.get("team") == "Statutory" and bucket(t) == "resolved"),
        "baseline": baseline or {},
    }
    return {
        "impact": impact,
        "tickets": len(rows),
        "support_tickets": work,
        "buckets": [{"key": b, "label": LABEL[b], "n": by[b]} for b in BUCKETS],
        "resolved_by_agent_rate": round(by["resolved"] / work, 3) if work else None,
        "confidence": {"average": round(sum(confs) / len(confs), 3) if confs else None,
                       "bands": [bands[label] for _, label in BANDS if label in bands]},
        "answer_path": {
            "tiers": [{"key": k, "n": v} for k, v in tiers.most_common()],
            "howto_tickets": len(howto),
            "howto_from_library": howto_tiers["library"], "howto_from_cache": howto_tiers["cache"],
            "howto_from_rag": howto_tiers["model"] + howto_tiers["fallback"],
            "cache_hit_rate": round(howto_tiers["cache"] / len(howto), 3) if howto else None,
            "avg_cache_similarity": round(sum(cache_sims) / len(cache_sims), 3) if cache_sims else None,
            "avg_top_rag_score": round(sum(top_rag) / len(top_rag), 2) if top_rag else None,
        },
        "guard": {"drafts_checked": len(guards), "passed": sum(1 for g in guards if g.get("ok")),
                  "model_drafts_replaced": sum(1 for g in guards if g.get("replaced_model_draft")),
                  "failed_checks": [{"key": k, "n": v} for k, v in failed.most_common()]},
        "approvals": {"waiting": by["approval"],
                      "approved_as_is": sum(1 for t in reviewed if t["review_outcome"] == "approved_as_is"),
                      "edited": sum(1 for t in reviewed if t["review_outcome"] == "edited"),
                      "rejected": sum(1 for t in reviewed if t["review_outcome"] == "rejected"),
                      "median_minutes_to_decide": round(median(minutes), 1) if minutes else None},
        "feedback": {"solved": sum(1 for t in rows if t.get("feedback") == "yes"),
                     "not_solved": sum(1 for t in rows if t.get("feedback") == "no")},
        "languages": [{"key": k or "(unknown)", "n": v} for k, v in Counter(t.get("language") for t in rows).most_common()],
        "model_cost_usd": round(cost_usd, 4),
    }


def queue_rows(rows: list[dict], view: str, language: str | None = None, team: str | None = None) -> list[dict]:
    out = []
    for t in rows:
        b = bucket(t)
        if view != "all" and b != view:
            continue
        if language and t.get("language") != language:
            continue
        if team and t.get("team") != team:
            continue
        d = t.get("decision") or {}
        out.append({"id": t["id"], "ref": t.get("ref"), "tier": t.get("tier"),
                    "priority": bool(((t.get("decision") or {}).get("classification") or {}).get("priority_signal")),
                    "seconds_to_answer": t.get("first_reply_seconds"), "cost_usd": t.get("cost_usd"), "created_at": str(t.get("created_at") or "")[:16],
                    "tenant_id": t.get("tenant_id"), "language": t.get("language"), "team": t.get("team"),
                    "confidence": _conf(t), "bucket": b, "route": t.get("route"), "rule": t.get("route_rule"),
                    "answered_by": (d.get("answer") or {}).get("tier") or t.get("answer_tier"),
                    "review_outcome": t.get("review_outcome"), "feedback": t.get("feedback"),
                    "has_translation": bool(t.get("translation")),
                    "preview": (t.get("masked_body") or "")[:140]})
    return out


ROW_CAP = 5000  # rows read per window; above it the console says the window is truncated
SORTS = {
    "newest": (lambda t: str(t.get("created_at") or ""), True),
    "priority": (lambda t: (bool(t.get("priority")), t.get("tier") == "Enterprise", str(t.get("created_at") or "")), True),
    "confidence": (lambda t: t["confidence"] if t.get("confidence") is not None else 2.0, False),
    "slowest": (lambda t: t["seconds_to_answer"] if t.get("seconds_to_answer") is not None else 1e12, True),
    "cost": (lambda t: t.get("cost_usd") or 0.0, True),
}


def page(rows: list[dict], view: str = "all", q: str | None = None, sort: str = "newest", limit: int = 50,
         offset: int = 0, language: str | None = None, team: str | None = None) -> dict:
    """One page of the queue, filtered and sorted on the server, with counts per outcome for the chips.
    Counts cover the whole window (search and language/team filters applied), not just the page."""
    base = queue_rows(rows, "all", language, team)
    if q:
        needle = q.lower()
        base = [t for t in base if needle in f"{t.get('preview')} {t.get('ref')} {t.get('team')} {t.get('tenant_id')}".lower()]
    counts = Counter(t["bucket"] for t in base)
    chosen = base if view == "all" else [t for t in base if t["bucket"] == view]
    key, reverse = SORTS.get(sort, SORTS["newest"])
    chosen = sorted(chosen, key=key, reverse=reverse)
    return {"view": view, "count": len(chosen), "counts": {"all": len(base), **{b: counts[b] for b in BUCKETS}},
            "offset": offset, "limit": limit, "tickets": chosen[offset: offset + limit],
            "truncated": len(rows) >= ROW_CAP}


# ---------------------------------------------------------------- engineering view (FDE, admin only)
PIPELINE = ("pii_gate", "normalise", "resolve_tenant", "classify", "dedupe", "route", "draft", "output_guard", "send")


def _q(xs: list[float], q: float):
    if not xs:
        return None
    xs = sorted(xs)
    return round(xs[min(len(xs) - 1, int(q * len(xs)))], 1)


def engineering(rows: list[dict], usage: list[dict] | None = None, slow_n: int = 10) -> dict:
    """Where the time goes per graph node, what failed, what the models cost, and a trace id per ticket.
    Built from the same decision records as the support view: ids, timings and labels, never ticket text."""
    work = [t for t in rows if (t.get("decision") or {}).get("timings_ms")]
    per = {n: [] for n in PIPELINE}
    totals = []
    for t in work:
        tm = t["decision"]["timings_ms"]
        for n, ms in tm.items():
            per.setdefault(n, []).append(float(ms))
        totals.append((sum(float(v) for v in tm.values()), t))
    nodes = [{"node": n, "n": len(v), "p50": _q(v, .5), "p95": _q(v, .95), "max": max(v) if v else None,
              "share": round(sum(v) / max(sum(x for x, _ in totals), 1e-9), 3)} for n, v in per.items() if v]
    ends = [x for x, _ in totals]

    def brief(t, ms=None):
        d = t.get("decision") or {}
        return {"id": t["id"], "ref": t.get("ref"), "route": t.get("route"), "status": t.get("agent_status"),
                "tier": (d.get("answer") or {}).get("tier"), "ms": round(ms, 1) if ms is not None else None,
                "trace_id": d.get("trace_id"), "slowest_node": max((d.get("timings_ms") or {"-": 0}).items(), key=lambda kv: kv[1])[0]}

    dec = [t.get("decision") or {} for t in rows]
    guard_fail = Counter(p for d in dec for p in (d.get("guard") or {}).get("failed") or [])
    failed = [t for t in rows if t.get("agent_status") == "failed"]
    first = [t["first_reply_seconds"] for t in rows if t.get("first_reply_seconds") is not None]
    u = usage or []
    return {
        "tickets": len(rows), "with_timings": len(work),
        "traced": sum(1 for d in dec if d.get("trace_id")),
        "end_to_end_ms": {"p50": _q(ends, .5), "p95": _q(ends, .95), "max": round(max(ends), 1) if ends else None},
        "first_reply_s": {"p50": _q(first, .5), "p95": _q(first, .95)},
        "nodes": nodes,
        "slowest": [brief(t, ms) for ms, t in sorted(totals, key=lambda x: -x[0])[:slow_n]],
        "failed": {"n": len(failed), "rows": [brief(t) for t in failed[:slow_n]]},
        "guard": {"blocked": sum(1 for d in dec if (d.get("guard") or {}).get("failed")),
                  "replaced": sum(1 for d in dec if (d.get("guard") or {}).get("replaced_model_draft")),
                  "by_check": [{"key": k, "n": n} for k, n in guard_fail.most_common()]},
        "classifier_model_rate": round(sum(1 for d in dec if (d.get("classification") or {}).get("model_called")) / max(len(dec), 1), 3),
        "injection": sum(1 for d in dec if (d.get("classification") or {}).get("injection")),
        "fallback": sum(1 for d in dec if (d.get("answer") or {}).get("tier") == "fallback"),
        "models": u,
        "model_calls": sum(r.get("calls", 0) for r in u),
        "model_cost_usd": round(sum(r.get("cost_usd", 0) for r in u), 4),
        "escalations": sum(r.get("calls", 0) for r in u if (r.get("rung") or 0) > 0),
    }
