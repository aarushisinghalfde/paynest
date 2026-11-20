"""Parse each data-room file into plain records (no masking, no database).

The ticket export holds three formats in one list (email helpdesk, in-app widget, partner
portal); each is mapped onto one shape. Staff data is minimised on the way in: agent names
and the names in "approved_by" are dropped; agents stay as their AG-nnn ids.
"""

import csv
import io
import re
from dataclasses import dataclass, field
from datetime import datetime

from loader.normalize import case_status, category_team, priority, queue_team
from loader.timeparse import IST, parse_ts

DUPLICATE_OF_RE = re.compile(r"duplicate of (PN-\d+)", re.I)


@dataclass
class Event:
    ts: datetime | None
    type: str
    actor: str | None
    data: dict


@dataclass
class TicketRec:
    ref: str
    source: str  # email | widget | partner
    tenant_id: str
    subject: str
    body: str
    category_raw: str | None
    priority: str | None
    case_status: str | None
    created_at: datetime | None
    first_response_at: datetime | None
    resolved_at: datetime | None
    events: list[Event]
    sender_email: str | None = None
    user_ref: str | None = None
    partner_id: str | None = None
    end_customer: str | None = None
    raw: dict = field(default_factory=dict, repr=False)

    # -- facts derived from the history ------------------------------------------------
    @property
    def initial_team(self) -> str | None:
        """The customer's original pick: the category on the 'created' event. (The ticket's
        top-level category field is the FINAL label in this export, not the original.)"""
        for e in self.events:
            team = category_team(e.data.get("category"))
            if team:
                return team
        return category_team(self.category_raw)

    @property
    def closing_team(self) -> str | None:
        """Category on the last event that carries one (the resolve event), normalised."""
        for e in reversed(self.events):
            team = category_team(e.data.get("category"))
            if team:
                return team
        return category_team(self.category_raw)

    @property
    def final_queue_team(self) -> str | None:
        """Last team queue the ticket was assigned to (L2 and Jira are not teams)."""
        for e in reversed(self.events):
            for key in ("to", "queue"):
                team = queue_team(e.data.get(key))
                if team:
                    return team
        return None

    @property
    def reassign_count(self) -> int:
        return sum(1 for e in self.events if e.type == "reassigned")

    @property
    def duplicate_of(self) -> str | None:
        for e in self.events:
            m = DUPLICATE_OF_RE.search(str(e.data.get("resolution", "")))
            if m:
                return m.group(1)
        return None

    @property
    def kb_ids(self) -> list[str]:
        return sorted({e.data["kb_article_id"] for e in self.events if e.data.get("kb_article_id")})


def _events(items, type_key, ts_key, actor_key, data_key, naive_tz=IST) -> list[Event]:
    out = []
    for e in items or []:
        out.append(
            Event(
                parse_ts(e.get(ts_key), naive_tz),
                str(e.get(type_key, "")).lower(),
                e.get(actor_key),
                dict(e.get(data_key) or {}),
            )
        )
    return out


def parse_ticket(r: dict) -> TicketRec:
    if "ticket_id" in r:  # email helpdesk
        return TicketRec(
            ref=r["ticket_id"],
            source="email",
            tenant_id=r["customer_id"],
            subject=r.get("subject") or "",
            body=r.get("body") or "",
            category_raw=r.get("category"),
            priority=priority(r.get("priority")),
            case_status=case_status(r.get("status")),
            created_at=parse_ts(r.get("received_at")),
            first_response_at=parse_ts(r.get("first_response_at")),
            resolved_at=parse_ts(r.get("resolved_at")),
            events=_events(r.get("events"), "event", "ts", "actor", "meta"),
            sender_email=r.get("from_email"),
            raw=r,
        )
    if "tkt" in r:  # in-app widget
        return TicketRec(
            ref=r["tkt"],
            source="widget",
            tenant_id=r["org_id"],
            subject=r.get("title") or "",
            body=r.get("message") or "",
            category_raw=r.get("cat"),
            priority=priority(r.get("prio")),
            case_status=case_status(r.get("state")),
            created_at=parse_ts(r.get("created")),
            first_response_at=parse_ts(r.get("first_reply_ts")),
            resolved_at=parse_ts(r.get("closed_ts")),
            events=_events(r.get("history"), "action", "time", "who", "data"),
            user_ref=r.get("user_ref"),
            raw=r,
        )
    if "reference" in r:  # partner portal
        return TicketRec(
            ref=r["reference"],
            source="partner",
            tenant_id=r["tenant"],
            subject=r.get("summary") or "",
            body=r.get("details") or "",
            category_raw=r.get("topic"),
            priority=priority(r.get("severity")),
            case_status=case_status(r.get("status")),
            created_at=parse_ts(r.get("opened_on")),
            first_response_at=parse_ts(r.get("fr_at")),
            resolved_at=parse_ts(r.get("closed_at")),
            events=_events(r.get("activity_log"), "evt", "when", "user", "info"),
            partner_id=r.get("partner_id"),
            end_customer=r.get("end_customer"),
            raw=r,
        )
    raise ValueError("unknown ticket format: keys " + ",".join(sorted(r)[:6]))


def parse_tickets(export: dict) -> list[TicketRec]:
    return [parse_ticket(r) for r in export["tickets"]]


def dedupe_exact(tickets: list[TicketRec]) -> tuple[list[TicketRec], list[str]]:
    """Drop repeated rows of the same ticket (the export script wrote some twice).

    Keeps the first row. A later row with the same reference must be the same ticket: same
    format, subject and body (only the status may differ); anything else is an error, not a
    duplicate. Resubmits (a customer writing again, with a new reference) are NOT dropped
    here: they are real tickets, handled by dedupe in phase 7.
    """
    seen: dict[str, TicketRec] = {}
    dropped = []
    for t in tickets:
        first = seen.get(t.ref)
        if first is None:
            seen[t.ref] = t
            continue
        if (first.source, first.subject, first.body) != (t.source, t.subject, t.body):
            raise ValueError(f"{t.ref} appears twice with different content")
        dropped.append(t.ref)
    return list(seen.values()), dropped


# ---------------------------------------------------------------- other sources
def _csv(text: str) -> list[dict]:
    return list(csv.DictReader(io.StringIO(text)))


def _num(v, cast=float):
    return cast(v) if v not in (None, "") else None


def parse_customers(text: str) -> list[dict]:
    rows = []
    for r in _csv(text):
        rows.append(
            {
                "tenant_id": r["customer_id"],
                "name": r["name"],
                "tier": r["tier"],
                "region": r["region"],
                "monthly_fee_usd": _num(r["monthly_fee_usd"]),
                "employees_paid": _num(r["employees_paid"], int),
            }
        )
    return rows


def parse_agents(text: str) -> list[dict]:
    """Names are dropped (data minimisation): tickets refer to agents by id only."""
    return [
        {
            "agent_id": r["agent_id"],
            "tier": r["tier"],
            "desk": r["desk"],
            "languages": [x.strip() for x in r["languages"].split(",") if x.strip()],
            "hire_date": r["hire_date"] or None,
            "status": r["status"],
            "left_date": r["left_date"] or None,
        }
        for r in _csv(text)
    ]


def parse_csat(text: str) -> list[dict]:
    return [
        {
            "survey_id": r["survey_id"],
            "ticket_ref": r["ticket_id"] or None,
            "customer_id": r["customer_id"],
            "score": _num(r["score"], int),
            "comment": r["comment"] or None,
            "submitted_at": parse_ts(r["submitted_at"]),
            "survey_channel": r["survey_channel"],
        }
        for r in _csv(text)
    ]


def parse_sla_breaches(text: str) -> list[dict]:
    rows = []
    for r in _csv(text):
        who = (r.get("approved_by") or "").strip()
        rows.append(
            {
                "breach_id": r["breach_id"],
                "ticket_ref": r["ticket_id"],
                "customer_id": r["customer_id"],
                "tier": r["tier"],
                "priority": r["priority"],
                "sla_resolution_target_h": _num(r["sla_resolution_target_h"]),
                "actual_resolution_h": _num(r["actual_resolution_h"]),
                "breach_h": _num(r["breach_h"]),
                "credit_pct": _num(r["credit_pct"]),
                "monthly_fee_usd": _num(r["monthly_fee_usd"]),
                "credit_usd": _num(r["credit_usd"]),
                "invoice_month": r["invoice_month"],
                "agent_noted_reason": r["agent_noted_reason"] or None,
                # who approved is a person's name: keep only whether a person or the system did it
                "approved_by_kind": None if not who else ("system" if "auto" in who.lower() else "person"),
            }
        )
    return rows


def parse_costs(text: str) -> list[dict]:
    out = []
    for r in _csv(text):
        row = {"month": r["month"], "notes": r.get("notes") or None}
        for k, v in r.items():
            if k not in ("month", "notes"):
                row[k] = _num(v)
        out.append(row)
    return out


def parse_whatsapp(items: list) -> list[dict]:
    return [
        {
            "thread_id": t["thread_id"],
            "ticket_ref": t.get("ticket_id"),
            "wa_contact": t.get("wa_contact"),
            "customer_hint": t.get("customer_hint"),
            "closed": bool(t.get("closed")),
            "messages": [
                {"sender": m.get("from"), "ts": parse_ts(m.get("ts")), "text": m.get("text") or ""}
                for m in t.get("messages", [])
            ],
        }
        for t in items
    ]


def parse_calls(items: list) -> list[dict]:
    return [
        {
            "call_id": c["call_id"],
            "ticket_ref": c.get("ticket_id"),
            "agent_id": c.get("agent_id"),
            "customer_id": c.get("customer_id"),
            "called_at": parse_ts(c.get("called_at")),
            "duration_min": c.get("duration_min"),
            "summary": c.get("summary") or "",
            "disposition": c.get("disposition"),
            "callback_required": bool(c.get("callback_required")),
        }
        for c in items
    ]


def parse_jira(items: list) -> list[dict]:
    return [
        {
            "key": j["key"],
            "summary": j.get("summary") or "",
            "issue_type": j.get("issue_type"),
            "priority": j.get("priority"),
            "component": j.get("component"),
            "status": j.get("status"),
            "created_at": parse_ts(j.get("created")),
            "reporter_agent": j.get("reporter"),
            "customer_ids": j.get("customer_ids") or [],
            "linked_ticket_refs": j.get("linked_ticket_ids") or [],
            "resolution_note": j.get("resolution_note") or "",
        }
        for j in items
    ]


# ---------------------------------------------------------------- SLA contract excerpt
_TIER_ROW = re.compile(r"^\|\s*\*\*(\w+)\*\*\s*\|.*?\|.*?\|\s*(.*?)\s*\|\s*(.*?)\s*\|\s*(\w+)\s*\|", re.M)
_CREDIT_ROW = re.compile(
    r"^\|\s*(Enterprise|Business)\s*\|\s*([\d.]+)%\s*\|\s*([\d.]+)%\s*\|\s*([\d.]+)%\s*\|", re.M
)
_HOURS = re.compile(r"(P[123]):\s*([\d.]+)\s*h")


def parse_sla_terms(md: str) -> list[dict]:
    """sla_contract_excerpt.md -> one row per (tier, priority). Standard is best effort (no targets)."""
    version = re.search(r"Template v([\d.]+)", md)
    version = version.group(1) if version else None
    credits = {
        m.group(1): dict(zip(("P1", "P2", "P3"), map(float, m.groups()[1:]), strict=True))
        for m in _CREDIT_ROW.finditer(md)
    }
    multiplier = re.search(r"exceeds \*\*twice\*\* the target.*?multiplied by \*\*([\d.]+)\*\*", md, re.S)
    rows = []
    for m in _TIER_ROW.finditer(md):
        tier, first, resolution, has_credits = m.groups()
        fr, res = dict(_HOURS.findall(first)), dict(_HOURS.findall(resolution))
        for p in ("P1", "P2", "P3"):
            rows.append(
                {
                    "template_version": version,
                    "tier": tier,
                    "priority": p,
                    "first_response_h": _num(fr.get(p)),
                    "resolution_h": _num(res.get(p)),
                    "credit_pct": credits.get(tier, {}).get(p) if has_credits.lower() == "yes" else None,
                    "severity_multiplier": float(multiplier.group(1)) if multiplier else None,
                }
            )
    return rows
