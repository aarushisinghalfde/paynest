"""Phase 4 loader on a synthetic data room (the client data never reaches CI)."""

import re
import time
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from intake.vault import MemoryVault
from loader import build as builder
from loader import db, knowledge, labelled, routing, sources, verify
from loader.normalize import TEAMS, category_team, language, priority
from loader.timeparse import parse_ts
from tests.fixtures import dataroom_synthetic as syn

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def built():
    vault = MemoryVault()
    ds = builder.build(syn.raw(), vault, b"test-key", "ap-southeast-2", int(time.time()))
    return ds, vault


# ---------------------------------------------------------------- timestamps
@pytest.mark.parametrize(
    "value,expected",
    [
        ("2026-08-10T09:36:23+05:30", datetime(2026, 8, 10, 4, 6, 23, tzinfo=UTC)),
        ("2026-08-10T09:36:23Z", datetime(2026, 8, 10, 9, 36, 23, tzinfo=UTC)),
        ("2026-08-10T09:36:23", datetime(2026, 8, 10, 4, 6, 23, tzinfo=UTC)),  # naive = IST
        ("2026-08-10 09:36:23", datetime(2026, 8, 10, 4, 6, 23, tzinfo=UTC)),
        ("01/08/2026 13:05 GST", datetime(2026, 8, 1, 9, 5, tzinfo=UTC)),
        ("01/08/2026 13:05 IST", datetime(2026, 8, 1, 7, 35, tzinfo=UTC)),
        ("20-07-2026 11:19", datetime(2026, 7, 20, 5, 49, tzinfo=UTC)),
        (1786354200000, datetime(2026, 8, 10, 9, 30, tzinfo=UTC)),
    ],
)
def test_every_timestamp_format_becomes_utc(value, expected):
    assert parse_ts(value) == expected


def test_missing_timestamps_and_garbage():
    assert parse_ts(None) is None and parse_ts("") is None
    with pytest.raises(ValueError):
        parse_ts("next tuesday")


# ---------------------------------------------------------------- labels
SPELLINGS = {  # the 35 spellings seen in the export
    "Payroll": ["Payroll", "payroll-run", "PAYROLL ISSUE", "Payroll Run"],
    "Statutory": ["Statutory", "statutory/compliance", "Compliance - PF/WPS", "STATUTORY"],
    "How-To": ["How-To", "how to", "HowTo", "how_to"],
    "Reports": ["Reports", "reports", "Report / Export", "REPORTS"],
    "Leave & Attendance": ["Leave & Attendance", "leave-attendance", "Leave/Attendance", "LEAVE"],
    "Integration": ["Integration", "integrations", "API / Integration", "INTEGRATION BUG"],
    "Billing": ["Billing", "billing", "Billing & Invoices", "BILLING"],
    "Access / Login": ["Access / Login", "access-login", "Login Issue", "ACCESS"],
    "Onboarding": ["Onboarding", "onboarding", "New Customer Setup"],
}


def test_35_spellings_map_to_the_9_sop_teams():
    assert sum(map(len, SPELLINGS.values())) == 35 and set(SPELLINGS) == set(TEAMS)
    for team, spellings in SPELLINGS.items():
        assert {category_team(s) for s in spellings} == {team}
    assert category_team("Something else") is None


def test_priority_and_language():
    assert [priority(p) for p in ("P1", "urgent", "high", "normal", "S1", "S3")] == [
        "P1",
        "P1",
        "P2",
        "P3",
        "P1",
        "P3",
    ]
    assert language("Salary nahi aayi, kya hua hai?") == "hi-Latn"
    assert language("Please check my payslip") == "en"
    assert language("वेतन जमा नहीं हुआ") == "hi" and language("لم يتم تحويل الراتب") == "ar"


# ---------------------------------------------------------------- parsing
def test_three_formats_one_shape_and_original_pick_comes_from_the_created_event():
    t = {x.ref: x for x in sources.parse_tickets(syn.tickets())}
    assert {x.source for x in t.values()} == {"email", "widget", "partner"}
    first = t["PN-900001"]
    assert first.category_raw == "Statutory"  # top-level field = the FINAL label
    assert first.initial_team == "Payroll"  # the customer's pick, from the created event
    assert first.closing_team == first.final_queue_team == "Statutory"
    assert first.reassign_count == 1 and first.kb_ids == ["KB-9142"]
    assert t["PN-900004"].duplicate_of == "PN-900001"


def test_exact_repeats_dropped_but_resubmits_kept():
    unique, dropped = sources.dedupe_exact(sources.parse_tickets(syn.tickets()))
    assert dropped == ["PN-900001"] and len(unique) == 5
    assert any(x.ref == "PN-900004" for x in unique)


def test_same_reference_with_different_content_is_an_error():
    data = syn.tickets()
    data["tickets"][-1] = dict(data["tickets"][-1], body="something else")
    with pytest.raises(ValueError, match="different content"):
        sources.dedupe_exact(sources.parse_tickets(data))


def test_sla_terms_parsed_from_the_contract_excerpt():
    rows = {
        (r["tier"], r["priority"]): r
        for r in sources.parse_sla_terms(syn.raw()["data-room/process/sla_contract_excerpt.md"])
    }
    assert rows[("Enterprise", "P1")] == {
        "template_version": "3.2",
        "tier": "Enterprise",
        "priority": "P1",
        "first_response_h": 1.0,
        "resolution_h": 8.0,
        "credit_pct": 10.0,
        "severity_multiplier": 1.5,
    }
    assert rows[("Standard", "P2")]["resolution_h"] is None and rows[("Standard", "P2")]["credit_pct"] is None


def test_staff_names_are_not_kept():
    raw = syn.raw()
    agents = sources.parse_agents(raw["data-room/data/agent_roster.csv"])
    assert "name" not in agents[0] and agents[0]["languages"] == ["en", "hi"]
    breach = sources.parse_sla_breaches(raw["data-room/data/sla_breaches_q3.csv"])[0]
    assert "approved_by" not in breach and breach["approved_by_kind"] == "person"


# ---------------------------------------------------------------- the build: masked, complete, routed
def test_no_raw_value_in_any_table(built):
    ds, _ = built
    scan = verify.leak_scan(syn.raw(), ds.tables)
    assert scan["leaks_by_table"] == {}
    text = "\n".join(builder.all_text(rows) for rows in ds.tables.values())
    for value in syn.PII.values():
        assert value not in text and builder.strip_ws(value) not in builder.strip_ws(text)


def test_raw_values_are_in_the_vault_for_their_own_record(built):
    ds, vault = built
    t = next(x for x in ds.tables["tickets"] if x["ticket_ref"] == "PN-900001")
    tokens = re.findall(r"<[A-Z_]+_\d+>", t["masked_body"])
    assert {vault.reveal(t["id"], tok) for tok in tokens} >= {syn.PII["aadhaar"], syn.PII["pan"]}
    assert vault.reveal(t["id"], "<SENDER_EMAIL>") == syn.PII["email"]
    assert t["sender_email_token"].startswith("em_")


def test_event_notes_masked_with_the_same_tokens_as_the_ticket(built):
    ds, _ = built
    tid = next(x["id"] for x in ds.tables["tickets"] if x["ticket_ref"] == "PN-900001")
    note = next(e for e in ds.tables["ticket_events"] if e["ticket_id"] == tid and e["type"] == "replied")
    assert syn.PII["acct"] not in note["data"]["note"] and "<ACCOUNT_1>" in note["data"]["note"]


def test_partner_ticket_tenant_resolved_by_company_name(built):
    ds, _ = built
    t = next(x for x in ds.tables["tickets"] if x["ticket_ref"] == "PN-900003")
    assert t["tenant_id"] == "C-9003" and t["tenant_resolved_by"] == "name" and t["language"] == "hi-Latn"


def test_hindi_onboarding_question_is_not_over_masked(built):
    ds, _ = built
    t = next(x for x in ds.tables["tickets"] if x["ticket_ref"] == "PN-900005")
    assert t["subject_masked"] == "नया कर्मचारी कैसे जोड़ें" and t["pii_counts"] == {}


def test_ids_are_deterministic_so_a_rerun_writes_the_same_rows():
    a = builder.build(syn.raw(), MemoryVault(), b"k", "ap-southeast-2", 0)
    b = builder.build(syn.raw(), MemoryVault(), b"k", "ap-southeast-2", 0)
    assert [t["id"] for t in a.tables["tickets"]] == [t["id"] for t in b.tables["tickets"]]


def test_gates_pass_on_the_synthetic_room(built):
    ds, _ = built
    results = {g: (ok, d) for g, ok, d in verify.gates(syn.raw(), ds.tables, expected_tickets=5)}
    assert all(ok for ok, _ in results.values()), results


def test_leak_gate_fails_if_a_value_slips_through(built):
    ds, _ = built
    tables = {k: [dict(r) for r in v] for k, v in ds.tables.items()}
    tables["call_notes"][0]["summary_masked"] = f"Caller asked about IFSC {syn.PII['ifsc']}"
    assert verify.leak_scan(syn.raw(), tables)["leaks_by_table"] == {"call_notes": 1}


def test_load_refuses_a_region_its_routing_table_does_not_send_tenants_to():
    with pytest.raises(RuntimeError, match="refusing to load"):
        builder.build(syn.raw(), MemoryVault(), b"k", "ap-south-1", 0, routing_table="demo")
    ds = builder.build(syn.raw(), MemoryVault(), b"k", "ap-south-1", 0, routing_table="production")
    assert {t["region"] for t in ds.tables["tenants"]} == {"IN"}  # India's region loads India only


def test_routing_tables():
    assert routing.home_region("IN") == "ap-south-1" and routing.home_region("UAE") == "me-central-1"
    assert {routing.serving_region(c, "demo") for c in ("IN", "UAE")} == {"ap-southeast-2"}


# ---------------------------------------------------------------- knowledge by date
def test_old_rule_before_its_date_new_rule_from_it(built):
    ds, _ = built
    chunks, rules = ds.tables["kb_chunks"], ds.tables["statutory_rules"]

    def kinds(topic, region, d):
        return {c["source_kind"] for c in knowledge.chunks_as_of(chunks, topic, region, d)} - {"kb_title"}

    assert kinds("pf_wage_ceiling", "IN", date(2026, 7, 31)) == {"kb_excerpt"}
    assert kinds("pf_wage_ceiling", "IN", date(2026, 8, 1)) == {"rule"}
    assert kinds("wps_file_format", "UAE", date(2026, 7, 14)) == {"kb_excerpt"}
    assert kinds("wps_file_format", "UAE", date(2026, 7, 15)) == {"rule"}
    assert kinds("pf_wage_ceiling", "UAE", date(2026, 8, 1)) == set()  # region filter
    assert (
        knowledge.get_rate(rules, "IN", "pf_wage_ceiling", date(2026, 7, 31))["value"]
        == "INR 15,000 per month"
    )
    assert (
        knowledge.get_rate(rules, "IN", "pf_wage_ceiling", date(2026, 8, 1))["value"]
        == "INR 25,000 per month"
    )
    old = next(c for c in chunks if c["chunk_id"] == "KB-9142#excerpt")
    assert old["effective_to"] == date(2026, 7, 31) and old["superseded_by"] == "R-IN-PF-2026-08#rule"


def test_process_docs_chunked_by_section(built):
    ds, _ = built
    ids = {c["chunk_id"] for c in ds.tables["kb_chunks"] if c["source_kind"] == "process_doc"}
    assert "process/escalation_policy#not-allowed" in ids


# ---------------------------------------------------------------- labelled set
def test_labelled_set_is_stratified_masked_and_skips_resubmits(built):
    ds, _ = built
    chosen = labelled.stratified(ds.tables["tickets"], n=10)
    refs = {t["ticket_ref"] for t in chosen}
    assert "PN-900004" not in refs  # resubmit
    assert {t["team"] for t in chosen} == {"Statutory", "How-To", "Onboarding"}
    rows = labelled.export_rows(chosen, {t["tenant_id"]: t for t in ds.tables["tenants"]})
    assert all(syn.PII["pan"] not in r["body"] for r in rows)
    assert next(r for r in rows if r["ticket_ref"] == "PN-900001")["moved"] is True


# ---------------------------------------------------------------- schema matches the rows
def _migration_columns() -> dict[str, set[str]]:
    sql = "\n".join(p.read_text(encoding="utf-8") for p in sorted((ROOT / "db" / "migrations").glob("*.sql")))
    cols: dict[str, set[str]] = {}
    for m in re.finditer(r"CREATE TABLE IF NOT EXISTS (\w+) \((.*?)\n\);", sql, re.S):
        cols[m.group(1)] = {
            ln.split()[0]
            for ln in m.group(2).splitlines()
            if ln.strip() and not ln.strip().startswith(("--", "PRIMARY", "UNIQUE"))
        }
    for m in re.finditer(r"ADD COLUMN IF NOT EXISTS (\w+)", sql):
        cols["tickets"].add(m.group(1))
    return cols


def test_every_loaded_column_exists_in_the_migrations(built):
    ds, _ = built
    cols = _migration_columns()
    for table, rows in ds.tables.items():
        assert table in db.KEYS, table
        missing = set(rows[0]) - cols[table]
        assert not missing, f"{table}: {missing}"


def test_upsert_sql_updates_non_key_columns():
    sql = db.upsert_sql("sla_terms", ["template_version", "tier", "priority", "resolution_h"])
    assert sql.endswith(
        "ON CONFLICT (template_version, tier, priority) DO UPDATE SET resolution_h = EXCLUDED.resolution_h"
    )
