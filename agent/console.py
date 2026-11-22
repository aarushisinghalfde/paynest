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


def summarize(rows: list[dict], cost_usd: float = 0.0) -> dict:
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
    return {
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
        out.append({"id": t["id"], "ref": t.get("ref"), "created_at": str(t.get("created_at") or "")[:16],
                    "tenant_id": t.get("tenant_id"), "language": t.get("language"), "team": t.get("team"),
                    "confidence": _conf(t), "bucket": b, "route": t.get("route"), "rule": t.get("route_rule"),
                    "answered_by": (d.get("answer") or {}).get("tier") or t.get("answer_tier"),
                    "review_outcome": t.get("review_outcome"), "feedback": t.get("feedback"),
                    "has_translation": bool(t.get("translation")),
                    "preview": (t.get("masked_body") or "")[:140]})
    return out
