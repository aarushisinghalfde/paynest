"""Replay Q3 tickets in time order through dedupe, incidents, Jira matching and injection.

Used for the phase 7 gate on the loaded (masked) data, on the EC2:
    docker compose run --rm --no-deps -T worker python -m agent.replay
Gold labels come from the data itself: resubmits carry "duplicate of PN-..." in their
history (26 pairs); the Meridian payslip burst is 25 Sep; PNJ-4412 lists its linked tickets.
"""
import json
import sys
from collections import defaultdict
from datetime import date

from agent import dedupe as dd
from agent import injection
from agent.dedupe import Recent

MARKER = "PHASE7_JSON="


def replay(tickets: list[dict], jira: list[dict]) -> dict:
    """tickets: masked export rows (ticket_ref, tenant_id, created_at, subject_masked, masked_body,
    duplicate_of_ref = the data's gold label). Returns the gate metrics."""
    by_tenant = defaultdict(list)
    incidents = defaultdict(list)
    predicted_dup, incident_of, opened_at_n, jira_of = {}, {}, {}, {}
    blocked = []
    issues_by_tenant = defaultdict(list)
    for j in jira:
        for c in j.get("customer_ids") or []:
            issues_by_tenant[c].append({"key": j["key"], "summary": j.get("summary_masked") or "",
                                        "resolution_note": j.get("resolution_note_masked") or ""})
    for t in sorted(tickets, key=lambda x: x["created_at"]):
        text = f"{t.get('subject_masked') or ''} {t.get('masked_body') or ''}"
        if injection.detect(text):
            blocked.append(t["ticket_ref"])
        recent = [r for r in by_tenant[t["tenant_id"]] if t["created_at"] - r.created_at <= dd.DUP_WINDOW]
        dup, _ = dd.find_duplicate(text, t["created_at"], recent)
        rec = Recent(t["ticket_ref"], t["ticket_ref"], t["created_at"], text)
        if dup:
            predicted_dup[t["ticket_ref"]] = dup
            rec.duplicate_of = dup
        else:
            inc = dd.find_incident(text, t["created_at"], recent, incidents[t["tenant_id"]])
            if inc.get("opened"):
                incidents[t["tenant_id"]].append({"id": inc["incident_id"], "signature": inc["signature"],
                                                  "opened_at": t["created_at"]})
                opened_at_n[inc["incident_id"]] = len(inc["members"]) + 1
                for m in inc["members"]:
                    incident_of[m] = inc["incident_id"]
                    for r in by_tenant[t["tenant_id"]]:
                        if r.ref == m:
                            r.incident_id = inc["incident_id"]
            if inc:
                incident_of[t["ticket_ref"]] = inc["incident_id"]
                rec.incident_id = inc["incident_id"]
            key = dd.match_jira(text, issues_by_tenant[t["tenant_id"]])
            if key:
                jira_of[t["ticket_ref"]] = key
        by_tenant[t["tenant_id"]].append(rec)

    gold = {t["ticket_ref"]: t["duplicate_of_ref"] for t in tickets if t.get("duplicate_of_ref")}
    true_pos = sum(1 for k, v in predicted_dup.items() if gold.get(k) == v)
    precision = true_pos / len(predicted_dup) if predicted_dup else 0.0
    recall = true_pos / len(gold) if gold else 0.0

    meridian = sorted((t for t in tickets if t["tenant_id"] == "C-1002" and t["created_at"].date() == date(2026, 9, 25)),
                      key=lambda x: x["created_at"])
    mer_incidents = {incident_of.get(t["ticket_ref"]) for t in meridian} - {None}
    first_n = min((opened_at_n[i] for i in mer_incidents if i in opened_at_n), default=None)
    pnj = next((j for j in jira if j["key"] == "PNJ-4412"), {})
    linked = set(pnj.get("linked_ticket_refs") or [])
    jira_hits = sum(1 for r in linked if jira_of.get(r) == "PNJ-4412")
    other_incidents = {i for t, i in incident_of.items() if i not in mer_incidents}
    return {
        "dedupe": {"gold_pairs": len(gold), "predicted": len(predicted_dup), "true": true_pos,
                   "precision": round(precision, 3), "recall": round(recall, 3)},
        "meridian": {"tickets_on_25_sep": len(meridian), "incidents": len(mer_incidents),
                     "opened_by_ticket_n": first_n,
                     "attached": sum(1 for t in meridian if incident_of.get(t["ticket_ref"]))},
        "other_incidents_opened": len(other_incidents),
        "pnj_4412": {"linked_in_jira": len(linked), "matched": jira_hits},
        "injection_blocked": blocked,
    }


def gates(m: dict) -> list[tuple[str, bool, str]]:
    d, mer, pnj = m["dedupe"], m["meridian"], m["pnj_4412"]
    return [
        ("dedupe_precision", d["precision"] >= 0.95,
         f"{d['true']}/{d['predicted']} predicted duplicates correct ({d['precision']:.0%}); "
         f"recall {d['recall']:.0%} of {d['gold_pairs']} resubmits"),
        ("meridian_incident", mer["incidents"] == 1 and (mer["opened_by_ticket_n"] or 99) <= 5,
         f"{mer['incidents']} incident(s) for {mer['tickets_on_25_sep']} tickets, opened at ticket "
         f"{mer['opened_by_ticket_n']}; {mer['attached']} attached; {m['other_incidents_opened']} other incidents"),
        ("pnj_4412_linked", pnj["matched"] >= 1,
         f"{pnj['matched']} of {pnj['linked_in_jira']} Kestrel tickets matched to PNJ-4412"),
        ("injection_blocked", "PN-101129" in m["injection_blocked"],
         f"blocked: {m['injection_blocked']}"),
    ]


def main() -> int:
    import psycopg

    from shared import settings

    with psycopg.connect(settings.DATABASE_URL) as conn:
        tickets = [r[0] for r in conn.execute("SELECT row_to_json(t) FROM tickets t WHERE origin = 'export'")]
        jira = [r[0] for r in conn.execute("SELECT row_to_json(j) FROM jira_issues j")]
    from datetime import datetime

    for t in tickets:
        t["created_at"] = datetime.fromisoformat(t["created_at"])
    m = replay(tickets, jira)
    out = {"metrics": m, "gates": [{"gate": g, "pass": ok, "detail": d} for g, ok, d in gates(m)]}
    print(MARKER + json.dumps(out, default=str))
    return 0 if all(g["pass"] for g in out["gates"]) else 1


if __name__ == "__main__":
    sys.exit(main())
