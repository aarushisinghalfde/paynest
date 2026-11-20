"""Phase 4 gates over a loaded dataset (from the builder, or read back from Postgres).

The leak scan does not trust the masker: it collects raw values from the RAW files with its
own broad patterns (any email, phone, 12-digit group, PAN/IFSC/Emirates ID/IBAN shape, long
number), plus structured fields (sender emails, WhatsApp numbers) and staff names, then
searches every value of every table for them.
"""

import json
import re
from datetime import date

from loader import knowledge, routing
from loader.build import FILES, all_text, strip_ws

ORACLE = [
    re.compile(r"[\w.+\-]+@[\w\-]+(?:\.[\w\-]+)+"),
    re.compile(r"(?<![A-Za-z0-9])[A-Z]{5}\d{4}[A-Z](?![A-Za-z0-9])"),  # PAN shape
    re.compile(r"(?<![A-Za-z0-9])[A-Z]{4}0[A-Z0-9]{6}(?![A-Za-z0-9])"),  # IFSC shape
    re.compile(r"(?<!\d)784[ \-]?\d{4}[ \-]?\d{7}[ \-]?\d(?!\d)"),  # Emirates ID shape
    re.compile(r"(?<![A-Za-z0-9])[A-Z]{2}\d{2}(?: ?\d{4}){4,7}(?: ?\d{1,4})?(?![A-Za-z0-9])"),  # IBAN shape
    re.compile(r"(?<!\d)\d{4}[ \-]?\d{4}[ \-]?\d{4}(?!\d)"),  # 12 digits (Aadhaar/UAN)
    re.compile(r"(?:\+91|\+971|00971)[ \-]?\d[\d \-]{7,12}\d"),  # phones with country code
    re.compile(r"(?<!\d)\d{9,18}(?!\d)"),  # long numbers
]
IGNORE = {"0" * 9}


def raw_values(raw: dict[str, str]) -> set[str]:
    def get(name):
        return raw[next(p for p in raw if p.endswith(FILES[name]))]

    texts = []
    for r in json.loads(get("tickets"))["tickets"]:
        texts += [r.get(k) or "" for k in ("subject", "body", "title", "message", "summary", "details")]
        for e in r.get("events") or r.get("history") or r.get("activity_log") or []:
            texts += [str(v) for v in (e.get("meta") or e.get("data") or e.get("info") or {}).values()]
    for w in json.loads(get("whatsapp")):
        texts += [m.get("text") or "" for m in w.get("messages", [])]
    texts += [c.get("summary") or "" for c in json.loads(get("calls"))]
    texts += [
        (j.get("summary") or "") + " " + (j.get("resolution_note") or "") for j in json.loads(get("jira"))
    ]
    texts += [get("csat"), get("sla_breaches")]
    values = {m.group().strip() for t in texts for rx in ORACLE for m in rx.finditer(t)}
    for r in json.loads(get("tickets"))["tickets"]:
        if r.get("from_email"):
            values.add(r["from_email"])
    values |= {w["wa_contact"] for w in json.loads(get("whatsapp")) if w.get("wa_contact")}
    roster = [line.split(",") for line in get("agents").splitlines()[1:] if line.strip()]
    values |= {row[1] for row in roster if len(row) > 1 and " " in row[1]}  # staff full names
    for line in get("sla_breaches").splitlines()[1:]:  # approvers' names
        who = line.rsplit(",", 1)[-1].strip()
        if who and "auto" not in who.lower():
            values.add(who)
    return {v for v in values if len(strip_ws(v)) >= 4 and v not in IGNORE}


def leak_scan(raw: dict[str, str], tables: dict[str, list[dict]]) -> dict:
    values = raw_values(raw)
    found = {}
    for name, rows in tables.items():
        text = all_text(rows)
        squashed = strip_ws(text)
        hits = [v for v in values if v in text or (len(strip_ws(v)) >= 8 and strip_ws(v) in squashed)]
        if hits:
            found[name] = len(hits)
    return {"raw_values_checked": len(values), "tables_scanned": len(tables), "leaks_by_table": found}


def date_checks(chunks: list[dict], rules: list[dict]) -> list[tuple[str, bool, str]]:
    """The old rule before its date, the new one from it: retrieval and get_rate."""
    out = []
    cases = [("pf_wage_ceiling", "IN", "R-IN-PF-2026-08"), ("wps_file_format", "UAE", "R-UAE-WPS-2026-07")]
    by_id = {r["rule_id"]: r for r in rules}
    for topic, region, rule_id in cases:
        day = by_id[rule_id]["effective_from"]
        before = [
            c["source_kind"]
            for c in knowledge.chunks_as_of(chunks, topic, region, date.fromordinal(day.toordinal() - 1))
            if c["source_kind"] != "kb_title"
        ]
        after = [
            c["source_kind"]
            for c in knowledge.chunks_as_of(chunks, topic, region, day)
            if c["source_kind"] != "kb_title"
        ]
        ok = set(before) == {"kb_excerpt"} and set(after) == {"rule"}
        r0 = knowledge.get_rate(rules, region, topic, date.fromordinal(day.toordinal() - 1))
        r1 = knowledge.get_rate(rules, region, topic, day)
        ok_rate = r0["value"] == by_id[rule_id]["old_value"] and r1["value"] == by_id[rule_id]["new_value"]
        out.append(
            (
                f"{topic}_by_date",
                ok and ok_rate,
                f"day before {day}: {sorted(set(before))}; from {day}: {sorted(set(after))}; "
                f"get_rate {r0['value']} -> {r1['value']}",
            )
        )
    return out


def gates(raw: dict[str, str], tables: dict[str, list[dict]], expected_tickets: int = 1353) -> list[tuple]:
    """[(gate, passed, detail)] for the phase 4 gate."""
    out = []
    tickets = tables["tickets"]
    out.append(
        (
            "ticket_count",
            len(tickets) == expected_tickets,
            f"{len(tickets)} unique tickets (expected {expected_tickets})",
        )
    )
    tenants = {t["tenant_id"]: t for t in tables["tenants"]}
    untagged = [t for t in tenants.values() if t.get("home_aws_region") not in ("ap-south-1", "me-central-1")]
    orphans = {t["tenant_id"] for t in tickets} - set(tenants)  # includes "unknown"
    out.append(
        (
            "tenants_tagged",
            not untagged and not orphans,
            f"{len(tenants)} tenants with a home region; {len(untagged)} untagged; "
            f"{len(orphans)} ticket tenants missing",
        )
    )
    demo = {routing.serving_region(t["region"], "demo") for t in tenants.values()}
    prod_ok = all(
        routing.serving_region(t["region"], "production")
        == {"IN": "ap-south-1", "UAE": "me-central-1"}[t["region"]]
        for t in tenants.values()
    )
    out.append(
        (
            "routing_tables",
            demo == {"ap-southeast-2"} and prod_ok,
            f"demo -> {sorted(demo)}; production -> India ap-south-1, UAE me-central-1: {prod_ok}",
        )
    )
    times = [t for t in tickets if t["created_at"] is None]
    out.append(
        (
            "timestamps_utc",
            not times,
            f"{len(tickets) - len(times)}/{len(tickets)} tickets have a UTC creation time",
        )
    )
    scan = leak_scan(raw, tables)
    blocked = sum(1 for t in tickets if t["status"] == "pii_blocked")
    out.append(
        (
            "leak_scan_all_tables",
            not scan["leaks_by_table"],
            f"{scan['raw_values_checked']} raw values, {scan['tables_scanned']} tables, "
            f"leaks {scan['leaks_by_table'] or 0}; {blocked} tickets quarantined",
        )
    )
    out += date_checks(tables["kb_chunks"], tables["statutory_rules"])
    return out
