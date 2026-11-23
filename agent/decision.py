"""Phase G1: the decision record - why the agent did what it did with one ticket, kept so a support
lead can read it later (console ticket timeline) without digging through checkpoints.

Built from the graph state at `send`. Masked text never goes in here: ids, labels, scores, rule ids,
check names and counts only. The ticket row already holds the masked question; replies are in
sent_replies.
"""

from shared.tracing import current_trace_id

GUARD_CHECKS = ("empty", "too_long", "pii_leak", "unknown_token", "bad_citation", "ungrounded_number",
                "uncited_answer", "wrong_region", "superseded_source", "instruction_leak", "promise",
                "wrong_language")



def _num(x, nd=3):
    try:
        return round(float(x), nd)
    except (TypeError, ValueError):
        return None


def _decided_by(c: dict, team) -> str | None:
    """Which layer settled the team, in words a lead can read."""
    src = c.get("source") or ""
    if "+statutory_figure" in src:
        return "rule: asks for a statutory figure"
    if "+run_status" in src:
        return "rule: payroll run status lookup"
    if "+howto_phrase" in src:
        return "tie-break: worded as a how-to question"
    if src == "conversation":
        return "conversation (no support topic)"
    layers = c.get("layers") or {}
    agree = [k for k in ("keywords", "similar", "model") if layers.get(k) and layers.get(k) == team]
    if c.get("model_called") and layers.get("model") == team:
        return "model, with " + (" and ".join(a for a in agree if a != "model") or "no other layer")
    if len(agree) >= 2:
        return " and ".join(agree) + " agree"
    if agree:
        return agree[0] + " (the other layer disagreed)" if any(layers.values()) else agree[0]
    return src or None


def _sim(x):
    v = _num(x)
    return None if v is None else min(v, 1.0)


def record(state: dict, outcome: str) -> dict:
    """outcome: sent | waiting_review | failed."""
    c = state.get("classification") or {}
    src = state.get("sources") or {}
    g = state.get("guard") or {}
    problems = [p.split(":")[0] for p in g.get("problems") or []]
    hits = src.get("hits") or []
    return {
        "v": 1,
        "outcome": outcome,
        "language": state.get("language"),
        "classification": {
            "team": state.get("team"), "confidence": _num(c.get("confidence")), "branch": c.get("branch"),
            "second": c.get("second"), "decided_by": _decided_by(c, state.get("team")),
            "layers": c.get("layers") or {}, "model_called": bool(c.get("model_called")),
            "injection": bool(c.get("is_injection")) or bool(state.get("injection_rules")),
            "priority_signal": bool(c.get("priority_signal")),
        },
        "merge": {
            "duplicate_of": state.get("duplicate_of"), "duplicate_reason": state.get("duplicate_reason") or None,
            "incident_id": state.get("incident_id"), "incident_size": state.get("incident_size"),
            "jira_key": state.get("jira_key"),
        },
        "route": {"route": state.get("route"), "rule": state.get("route_rule"), "reason": state.get("route_reason"),
                  "queue": state.get("queue")},
        "answer": {
            "tier": state.get("draft_mode"),
            "as_of": src.get("as_of"),
            # similarity of this question to the stored one, 0-1 (the matcher's score is capped at 1)
            "library_similarity": _sim(src.get("library_similarity")),
            "cache_similarity": _sim(src.get("cache_similarity")),
            "sources": [{"id": h.get("chunk_id"), "kb_id": h.get("kb_id"), "title": (h.get("title") or "")[:120],
                         "kind": h.get("source_kind"), "score": _num(h.get("score")), "solved": h.get("solved"),
                         "has_steps": h.get("has_steps")} for h in hits[:5]],
            "facts": [{"tool": f.get("tool"), "source": f.get("source"),
                       "result": f.get("status") or f.get("value") or f.get("error")
                       or (f"{f.get('tier')} tier, region {f.get('region')}" if f.get("tool") == "get_tenant_profile" else None)} for f in src.get("facts") or []],
            "citations": list(state.get("citations") or []),
            "learn_kb": list(state.get("learn_kb") or []),
        },
        "guard": {"ok": bool(g.get("ok")), "failed": problems,
                  "passed": [k for k in GUARD_CHECKS if k not in problems],
                  "replaced_model_draft": g.get("replaced") or None},
        "steps": list(state.get("steps") or []),
        "timings_ms": dict(state.get("timings") or {}),
        "trace_id": current_trace_id(),
        "tier": (state.get("tenant") or {}).get("tier"),
        "as_of": src.get("as_of"),
    }
