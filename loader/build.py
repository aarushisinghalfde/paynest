"""Raw data-room files -> masked table rows (pure: no database, no AWS).

Every free-text field passes the phase 3 gate before it becomes a row. One ticket is masked
as ONE document (subject, body and the free-text notes of its events), so the same value
gets the same token everywhere in that ticket. Raw values go to the vault under the
record's deterministic id (uuid5), so a re-run writes the same keys (the vault is
append-only, so a re-run adds nothing).
"""

import json
import re
import uuid
from dataclasses import dataclass, field
from types import SimpleNamespace

from intake.pipeline import ner_layer_name, rescan
from intake.tokens import sender_token
from loader import knowledge, routing, sources
from loader.normalize import language
from pii import mask_ticket

NS = uuid.UUID("6f1c9a52-6a1b-4d55-9a37-1d2b0a0c4e11")  # fixed namespace for record ids
SEP = "\n␞\n"  # field separator the masker never alters
FREE_TEXT_KEYS = ("note", "reason", "resolution", "text", "comment")

FILES = {  # path inside the uploaded zip (suffix match)
    "tickets": "data/tickets_export.json",
    "customers": "data/customers.csv",
    "agents": "data/agent_roster.csv",
    "csat": "data/csat_survey.csv",
    "sla_breaches": "data/sla_breaches_q3.csv",
    "costs": "data/monthly_cost_sheet.csv",
    "whatsapp": "data/whatsapp_export.json",
    "calls": "data/call_center_notes.json",
    "jira": "data/jira_escalations.json",
    "kb": "data/kb_articles.json",
    "rules": "integrations/statutory_rules.json",
    "sla_contract": "process/sla_contract_excerpt.md",
}
PROCESS_DOCS = "process/"


def record_id(kind: str, ref: str) -> str:
    return str(uuid.uuid5(NS, f"{kind}:{ref}"))


@dataclass
class Dataset:
    tables: dict[str, list[dict]] = field(default_factory=dict)
    summary: dict = field(default_factory=dict)
    vault_items: int = 0


class Masker:
    """mask_ticket over several fields at once, plus the re-scan, with counts."""

    def __init__(self, vault, hmac_key: bytes, ttl_s: int, now: int, mask=mask_ticket):
        self.vault, self.key, self.expires, self.mask = vault, hmac_key, now + ttl_s, mask
        self.blocked: list[str] = []
        self.counts: dict[str, int] = {}
        self.vaulted = 0

    def fields(
        self,
        rid: str,
        tenant: str,
        parts: list[str],
        sender_email=None,
        sender_phone=None,
        extra_values: dict | None = None,
    ) -> tuple[list[str] | None, dict]:
        """Mask parts together. Returns (masked parts, or None if the re-scan blocked them; counts)."""
        doc = SEP.join(p or "" for p in parts)
        r = self.mask(doc, sender_email=sender_email, sender_phone=sender_phone)
        inbox = SimpleNamespace(sender_email=sender_email, sender_phone=sender_phone, sender_name=None)
        if rescan(r.text, r.values, inbox):
            self.blocked.append(rid)
            return None, r.counts
        values = dict(r.values) | (extra_values or {})
        if values:
            self.vault.put(rid, tenant, values, self.expires)
            self.vaulted += len(values)
        for k, n in r.counts.items():
            self.counts[k] = self.counts.get(k, 0) + n
        out = r.text.split(SEP)
        if len(out) != len(parts):
            raise RuntimeError("masking changed the field separator")
        return out, r.counts


def _jsonable(v):
    return json.loads(json.dumps(v, default=str))


def build(
    raw: dict[str, str],
    vault,
    hmac_key: bytes,
    aws_region: str,
    now: int,
    routing_table: str = "demo",
    ttl_days: int = 3650,
    mask=mask_ticket,
) -> Dataset:
    """raw: {zip path: text}. Returns every phase 4 table as masked rows."""

    def get(name):
        path = next((p for p in raw if p.endswith(FILES[name])), None)
        if path is None:
            raise FileNotFoundError(FILES[name])
        return raw[path]

    m = Masker(vault, hmac_key, ttl_days * 86400, now, mask)
    ds = Dataset()

    # tenants, routed: a load only takes the tenants its routing table sends to this region
    tenants = sources.parse_customers(get("customers"))
    for t in tenants:
        t["home_aws_region"] = routing.home_region(t["region"])
    served = routing.tenants_served_here(tenants, aws_region, routing_table)
    if not served:
        raise RuntimeError(
            f"routing table '{routing_table}' sends no tenant to {aws_region}: refusing to load"
        )
    tenant_ids = {t["tenant_id"] for t in served}
    by_name = {t["name"].lower(): t["tenant_id"] for t in tenants}
    ds.tables["tenants"] = served

    # tickets
    parsed = sources.parse_tickets(json.loads(get("tickets")))
    unique, dropped = sources.dedupe_exact(parsed)
    resolved_by = {}
    for t in unique:  # partner tickets sometimes carry only the end customer's name
        if t.tenant_id:
            resolved_by[t.ref] = "id"
        elif (t.end_customer or "").lower() in by_name:
            t.tenant_id, resolved_by[t.ref] = by_name[t.end_customer.lower()], "name"
        else:
            t.tenant_id, resolved_by[t.ref] = "unknown", "unresolved"
    unique = [t for t in unique if t.tenant_id in tenant_ids or t.tenant_id == "unknown"]
    tickets, events, pii_tickets = [], [], 0
    layer = ner_layer_name()
    for t in unique:
        rid = record_id("ticket", t.ref)
        notes = [
            (i, k) for i, e in enumerate(t.events) for k in FREE_TEXT_KEYS if isinstance(e.data.get(k), str)
        ]
        parts = [t.subject, t.body] + [t.events[i].data[k] for i, k in notes]
        extra = {"<SENDER_EMAIL>": t.sender_email} if t.sender_email else {}
        masked, counts = m.fields(rid, t.tenant_id, parts, sender_email=t.sender_email, extra_values=extra)
        pii_tickets += bool(counts)
        evdata = [dict(e.data) for e in t.events]
        if masked:
            for (i, k), text in zip(notes, masked[2:], strict=True):
                evdata[i][k] = text
        tickets.append(
            {
                "id": rid,
                "ticket_ref": t.ref,
                "origin": "export",
                "tenant_id": t.tenant_id,
                "channel": t.source,
                "tenant_resolved_by": resolved_by[t.ref],
                "status": "masked" if masked else "pii_blocked",
                "subject_masked": masked[0] if masked else None,
                "masked_body": masked[1] if masked else None,
                "pii_counts": counts,
                "pii_block_reasons": [] if masked else ["loader_rescan"],
                "sender_email_token": sender_token(hmac_key, t.tenant_id, "email", t.sender_email),
                "user_ref": t.user_ref,
                "partner_id": t.partner_id,
                "end_customer": t.end_customer,
                "category_raw": t.category_raw,
                "initial_team": t.initial_team,
                "team": t.closing_team,
                "final_queue_team": t.final_queue_team,
                "reassign_count": t.reassign_count,
                "duplicate_of_ref": t.duplicate_of,
                "kb_ids": t.kb_ids,
                "priority": t.priority,
                "case_status": t.case_status,
                "language": language(f"{t.subject} {t.body}"),
                "created_at": t.created_at,
                "first_response_at": t.first_response_at,
                "resolved_at": t.resolved_at,
                "masked_at": None,
                "ner_layer": layer,
            }
        )
        for seq, (e, data) in enumerate(zip(t.events, evdata, strict=True)):
            events.append(
                {
                    "ticket_id": rid,
                    "seq": seq,
                    "ts": e.ts,
                    "type": e.type,
                    "actor": e.actor,
                    "data": _jsonable(data) if masked else {},
                }
            )
    ds.tables["tickets"] = tickets
    ds.tables["ticket_events"] = events

    # conversations and notes linked to tickets
    wa_threads, wa_messages = [], []
    for w in sources.parse_whatsapp(json.loads(get("whatsapp"))):
        tenant = by_name.get((w["customer_hint"] or "").lower(), "unknown")
        if tenant != "unknown" and tenant not in tenant_ids:
            continue
        rid = record_id("whatsapp", w["thread_id"])
        texts = [msg["text"] for msg in w["messages"]]
        extra = {"<SENDER_PHONE>": w["wa_contact"]} if w["wa_contact"] else {}
        masked, _ = m.fields(rid, tenant, texts, sender_phone=w["wa_contact"], extra_values=extra)
        wa_threads.append(
            {
                "id": rid,
                "thread_id": w["thread_id"],
                "ticket_ref": w["ticket_ref"],
                "tenant_id": tenant,
                "customer_hint": w["customer_hint"],
                "closed": w["closed"],
                "contact_token": sender_token(hmac_key, tenant, "phone", w["wa_contact"]),
                "pii_blocked": masked is None,
            }
        )
        for seq, msg in enumerate(w["messages"]):
            wa_messages.append(
                {
                    "thread_id": rid,
                    "seq": seq,
                    "sender": msg["sender"],
                    "ts": msg["ts"],
                    "text_masked": masked[seq] if masked else None,
                }
            )
    ds.tables["whatsapp_threads"], ds.tables["whatsapp_messages"] = wa_threads, wa_messages

    calls = []
    for c in sources.parse_calls(json.loads(get("calls"))):
        if c["customer_id"] not in tenant_ids:
            continue
        rid = record_id("call", c["call_id"])
        masked, _ = m.fields(rid, c["customer_id"], [c["summary"]])
        calls.append(
            {
                **{k: v for k, v in c.items() if k != "summary"},
                "id": rid,
                "summary_masked": masked[0] if masked else None,
            }
        )
    ds.tables["call_notes"] = calls

    jira = []
    for j in sources.parse_jira(json.loads(get("jira"))):
        rid = record_id("jira", j["key"])
        tenant = (j["customer_ids"] or ["unknown"])[0]
        masked, _ = m.fields(rid, tenant, [j["summary"], j["resolution_note"]])
        jira.append(
            {
                **{k: v for k, v in j.items() if k not in ("summary", "resolution_note")},
                "summary_masked": masked[0] if masked else None,
                "resolution_note_masked": masked[1] if masked else None,
            }
        )
    ds.tables["jira_issues"] = jira

    csat = []
    for s in sources.parse_csat(get("csat")):
        if s["customer_id"] not in tenant_ids:
            continue
        comment = None
        if s["comment"]:
            masked, _ = m.fields(record_id("csat", s["survey_id"]), s["customer_id"], [s["comment"]])
            comment = masked[0] if masked else None
        csat.append({**{k: v for k, v in s.items() if k != "comment"}, "comment_masked": comment})
    ds.tables["csat_responses"] = csat

    breaches = []
    for b in sources.parse_sla_breaches(get("sla_breaches")):
        if b["customer_id"] not in tenant_ids:
            continue
        reason = None
        if b["agent_noted_reason"]:
            masked, _ = m.fields(
                record_id("breach", b["breach_id"]), b["customer_id"], [b["agent_noted_reason"]]
            )
            reason = masked[0] if masked else None
        breaches.append(
            {**{k: v for k, v in b.items() if k != "agent_noted_reason"}, "agent_noted_reason_masked": reason}
        )
    ds.tables["sla_breaches"] = breaches

    # company knowledge and reference data (written by the company, not customers: not masked)
    ds.tables["agents"] = sources.parse_agents(get("agents"))
    ds.tables["monthly_costs"] = sources.parse_costs(get("costs"))
    ds.tables["sla_terms"] = sources.parse_sla_terms(get("sla_contract"))
    rules = json.loads(get("rules"))["rules"]
    ds.tables["statutory_rules"] = knowledge.rule_rows(rules)
    docs = {p: txt for p, txt in raw.items() if PROCESS_DOCS in p and p.endswith(".md")}
    ds.tables["kb_chunks"] = knowledge.build_chunks(json.loads(get("kb")), rules, docs)

    ds.vault_items = m.vaulted
    ds.summary = {
        "raw_ticket_rows": len(parsed),
        "exact_duplicates_dropped": len(dropped),
        "tickets": len(tickets),
        "tickets_with_pii": pii_tickets,
        "resubmits_flagged": sum(1 for t in tickets if t["duplicate_of_ref"]),
        "blocked_by_rescan": len(m.blocked),
        "vault_values": m.vaulted,
        "pii_counts": m.counts,
        "tenants": len(served),
        "routing_table": routing_table,
        "tenant_resolved_by": {
            k: sum(1 for v in resolved_by.values() if v == k) for k in ("id", "name", "unresolved")
        },
        "aws_region": aws_region,
        "rows": {k: len(v) for k, v in ds.tables.items()},
    }
    return ds


def all_text(rows: list[dict]) -> str:
    """Every value of every row as one string (for the leak scan)."""
    return "\n".join(json.dumps(r, default=str, ensure_ascii=False) for r in rows)


def strip_ws(s: str) -> str:
    return re.sub(r"[\s\-]", "", s)
