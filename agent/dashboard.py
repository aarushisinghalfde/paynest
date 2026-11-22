"""Operations dashboard: what the agent did, in numbers a support lead can read.

summarize(data, scope) turns the raw rows from store.dashboard_data into the JSON the
/dashboard page draws. Everything here is masked text, counts and ids; no personal data.

  live    tickets the agent handled: routes, teams, how confident the classification was and
          which layer decided, merges (duplicates, incidents, Jira), how each was resolved
          (approved answer, cache, RAG, template, human review), the learning loop.
  export  the client's Q3 history: final teams, customer pick vs final label, reassignments,
          resubmits, Jira links, the KB articles agents used.
"""

from collections import Counter

AUTO_ROUTES = {"reply", "chat", "ask", "incident", "duplicate", "block"}
TIER_LABEL = {"library": "Approved answer", "cache": "Answer cache", "model": "RAG + model",
              "fallback": "RAG (no model)", "template": "Template"}


def _top(counter: Counter, n: int = 12) -> list[dict]:
    return [{"key": k if k is not None else "(none)", "n": v} for k, v in counter.most_common(n)]


def _cls(t: dict) -> dict:
    c = t.get("classification") or {}
    return c if isinstance(c, dict) else {}


def summarize(data: dict, scope: str = "live") -> dict:
    tickets = data.get("tickets") or []
    n = len(tickets)
    out = {"scope": scope, "tickets": n, "by_team": _top(Counter(t.get("team") for t in tickets)),
           "by_language": _top(Counter(t.get("language") for t in tickets))}

    if scope == "export":
        picks = [t for t in tickets if t.get("initial_team") and t.get("team")]
        wrong = [t for t in picks if t["initial_team"] != t["team"]]
        pairs = Counter((t["initial_team"], t["team"]) for t in wrong)
        out["classification"] = {
            "customer_picks": len(picks), "customer_pick_wrong": len(wrong),
            "wrong_pairs": [{"picked": a, "final": b, "n": v} for (a, b), v in pairs.most_common(10)],
            "reassigned_more_than_once": sum(1 for t in tickets if (t.get("reassign_count") or 0) > 1),
        }
        out["merges"] = {
            "resubmits": sum(1 for t in tickets if t.get("duplicate_of")),
            "resubmit_examples": [{"ref": t["ref"], "of": t["duplicate_of"]} for t in tickets
                                  if t.get("duplicate_of")][:10],
            "jira_links": _top(Counter(t.get("jira_key") for t in tickets if t.get("jira_key")), 8),
        }
        out["resolution"] = {"kb_articles_used": _top(Counter(k for t in tickets for k in (t.get("kb_ids") or [])), 10)}
        return out

    cls = [_cls(t) for t in tickets]
    conf = [float(c["confidence"]) for c in cls if c.get("confidence") is not None]
    out["by_route"] = _top(Counter(t.get("route") for t in tickets))
    out["by_rule"] = _top(Counter(t.get("route_rule") for t in tickets), 15)
    out["classification"] = {
        "branches": _top(Counter(c.get("branch") for c in cls if c)),
        "decided_by": _top(Counter((c.get("source") or "").split("+")[0] or None for c in cls if c)),
        "avg_confidence": round(sum(conf) / len(conf), 3) if conf else None,
        "low_confidence": sum(1 for x in conf if x < 0.5),
    }
    incidents = data.get("incidents") or []
    out["merges"] = {
        "duplicates_linked": sum(1 for t in tickets if t.get("duplicate_of") or t.get("route") == "duplicate"),
        "incident_tickets": sum(1 for t in tickets if t.get("incident_id")),
        "incidents": [{"id": i["id"][:8], "tenant_id": i.get("tenant_id"), "team": i.get("team"),
                       "tickets": i.get("ticket_count"), "opened_at": str(i.get("opened_at") or "")[:16],
                       "signature": (i.get("signature") or "")[:90]} for i in incidents[:10]],
        "jira_links": _top(Counter(t.get("jira_key") for t in tickets if t.get("jira_key")), 8),
    }
    tiers = Counter(t.get("answer_tier") for t in tickets if t.get("answer_tier"))
    auto = [t for t in tickets if t.get("route") in AUTO_ROUTES and t.get("agent_status") == "replied"]
    howto = [t for t in tickets if t.get("team") == "How-To"]
    howto_auto = [t for t in howto if t.get("answer_tier") in ("library", "cache", "model", "fallback")
                  and t.get("agent_status") == "replied"]
    rv = data.get("reviews") or {}
    out["resolution"] = {
        "answered_automatically": len(auto),
        "waiting_for_review": sum(1 for t in tickets if t.get("agent_status") == "waiting_review"),
        "with_a_team": sum(1 for t in tickets if t.get("route") == "queue"),
        "answer_tiers": [{"key": TIER_LABEL.get(k, k), "n": v} for k, v in tiers.most_common()],
        "howto_tickets": len(howto),
        "howto_answered_by_agent": len(howto_auto),
        "howto_automation_rate": round(len(howto_auto) / len(howto), 3) if howto else None,
        "knowledge_tasks_open": rv.get("knowledge:open", 0),
        "knowledge_answers_written": rv.get("knowledge:approved", 0),
        "library_size": data.get("library_size", 0),
        "reviews": {"open": rv.get("reply:open", 0), "approved": rv.get("reply:approved", 0),
                    "rejected": rv.get("reply:rejected", 0)},
    }
    out["recent"] = [{"ref": t["ref"], "created_at": str(t.get("created_at") or "")[:16], "tenant_id": t.get("tenant_id"),
                      "team": t.get("team"), "route": t.get("route"), "rule": t.get("route_rule"),
                      "tier": TIER_LABEL.get(t.get("answer_tier"), t.get("answer_tier")),
                      "confidence": _cls(t).get("confidence"), "reason": t.get("route_reason")}
                     for t in tickets[:25]]
    return out
