"""Phase 8: retrieval by region and question date, tools, cited drafting, end to end."""

import io
import json
import urllib.error
from datetime import date, datetime

import pytest

from agent import drafter, tools
from agent.models import BudgetExceeded, Result
from agent.nodes import Deps
from agent.retrieval import Retriever, question_date
from agent.runner import MemoryCheckpoints, run
from agent.store import MemoryAgentStore
from agent.unmask import customer_view
from intake.vault import MemoryVault

RULES = [
    {"rule_id": "R-IN-PF-2026-08", "region": "IN", "topic": "pf_wage_ceiling", "title": "EPF statutory wage ceiling raised",
     "effective_from": "2026-08-01", "old_value": "INR 15,000 per month", "new_value": "INR 25,000 per month",
     "affects_kb_topics": ["pf_wage_ceiling"], "source": "EPFO"},
    {"rule_id": "R-UAE-WPS-2026-07", "region": "UAE", "topic": "wps_file_format", "title": "WPS SIF moves to v3",
     "effective_from": "2026-07-15", "old_value": "SIF v2 (14 columns)", "new_value": "SIF v3 (16 columns)",
     "affects_kb_topics": ["wps_file_format"], "source": "MOHRE"},
]
CHUNKS = [
    {"chunk_id": "KB-0201#excerpt", "source_kind": "kb_excerpt", "region": "IN", "topic": "pf_wage_ceiling",
     "title": "PF wage ceiling", "content": "PF wage ceiling is INR 15,000 per month of basic wages.",
     "effective_from": None, "effective_to": "2026-07-31", "superseded_by": "R-IN-PF-2026-08#rule"},
    {"chunk_id": "R-IN-PF-2026-08#rule", "source_kind": "rule", "region": "IN", "topic": "pf_wage_ceiling",
     "title": "EPF statutory wage ceiling raised", "content": "EPF wage ceiling. From 2026-08-01: INR 25,000 per month.",
     "effective_from": "2026-08-01", "effective_to": None},
    {"chunk_id": "R-UAE-WPS-2026-07#rule", "source_kind": "rule", "region": "UAE", "topic": "wps_file_format",
     "title": "WPS SIF moves to v3", "content": "WPS SIF file: from 2026-07-15 SIF v3 with 16 columns.",
     "effective_from": "2026-07-15", "effective_to": None},
    {"chunk_id": "KB-0101#title", "source_kind": "kb_title", "region": "ALL", "topic": "howto_onboard",
     "title": "Adding a new employee", "content": "KB-0101: Adding a new employee"},
]


@pytest.mark.parametrize("text,created,want", [
    ("PF for July payroll?", "2026-09-10", date(2026, 7, 1)),
    ("ceiling for Aug 2026", "2026-11-01", date(2026, 8, 1)),
    ("December salary", "2026-02-03", date(2025, 12, 1)),
    ("run on 2026-08-15 failed", "2026-09-01", date(2026, 8, 15)),
    ("no date here", datetime(2026, 9, 5, 10, 0), date(2026, 9, 5)),
])
def test_question_date(text, created, want):
    assert question_date(text, created) == want


def test_retrieval_respects_region_and_date():
    r = Retriever(CHUNKS, RULES)
    july = [h["chunk_id"] for h in r.search("PF wage ceiling", "IN", date(2026, 7, 1))]
    sept = [h["chunk_id"] for h in r.search("PF wage ceiling", "IN", date(2026, 9, 1))]
    assert "KB-0201#excerpt" in july and "R-IN-PF-2026-08#rule" not in july
    assert sept[0] == "R-IN-PF-2026-08#rule" and "KB-0201#excerpt" not in sept  # superseded excerpt gone
    assert not [h for h in r.search("WPS SIF file", "IN", date(2026, 9, 1)) if h["region"] == "UAE"]
    assert r.search("", "IN", date(2026, 9, 1)) == []


def test_tool_plan_only_uses_the_tenants_region():
    assert tools.plan("PF ceiling and WPS file", "IN")["rates"] == [("IN", "pf_wage_ceiling")]
    assert tools.plan("PF ceiling and WPS file", "UAE")["rates"] == [("UAE", "wps_file_format")]
    assert tools.plan("status of run PR-202609 please", "IN")["runs"] == ["PR-202609"]
    assert tools.plan("تم رفض ملف حماية الأجور", "UAE")["rates"] == [("UAE", "wps_file_format")]
    assert tools.plan("पीएफ की सीमा क्या है", "IN")["rates"] == [("IN", "pf_wage_ceiling")]


def test_get_rate_by_question_date():
    rules = Retriever(CHUNKS, RULES).rules
    assert tools.get_rate(rules, "IN", "pf_wage_ceiling", date(2026, 7, 1))["value"] == "INR 15,000 per month"
    assert tools.get_rate(rules, "IN", "pf_wage_ceiling", date(2026, 9, 1))["value"] == "INR 25,000 per month"


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_run_status_tool_handles_ok_rate_limit_and_down():
    ok = tools.get_run_status("PR-1", "http://p", opener=lambda u, timeout: _Resp(b'{"status": "processing"}'))
    assert ok["status"] == "processing" and ok["source"] == "payroll-api:PR-1"

    def limited(u, timeout):
        raise urllib.error.HTTPError(u, 429, "x", {}, io.BytesIO(b""))

    def down(u, timeout):
        raise urllib.error.URLError("no route")

    assert tools.get_run_status("PR-1", "http://p", opener=limited)["error"] == "rate_limited"
    assert tools.get_run_status("PR-1", "http://p", opener=down)["error"] == "unavailable"


def _state(text, region="IN"):
    return {"ticket_id": "t" * 32, "subject": "", "body": text, "language": "en",
            "tenant": {"tenant_id": "C-1", "region": region}, "meta": {"ticket_ref": "PN-1"}}


def test_fallback_draft_cites_the_value_for_the_question_date():
    r = Retriever(CHUNKS, RULES)
    st = _state("What is the PF wage ceiling for July payroll?")
    as_of = date(2026, 7, 1)
    d = drafter.draft(st, r.search(st["body"], "IN", as_of), tools.run_tools(st, r.rules, as_of, None), as_of)
    assert d["mode"] == "fallback" and "INR 15,000 per month" in d["reply"] and "2026-08-01" in d["reply"]
    assert "[R-IN-PF-2026-08#rule]" in d["reply"]
    assert drafter.draft(_state("hello there"), [], [], as_of) is None  # nothing factual: template


class FakeModel:
    def __init__(self, data=None, exc=None):
        self.data, self.exc, self.calls = data, exc, []

    def json_call(self, system, user, **kw):
        self.calls.append((system, user))
        if self.exc:
            raise self.exc
        return Result(self.data, "m", 1, 10, 10, 0.0, 5.0)


def test_model_draft_is_used_and_sees_only_masked_text_and_sources():
    m = FakeModel({"reply": "It is INR 25,000 per month [R-IN-PF-2026-08#rule].", "citations": ["R-IN-PF-2026-08#rule"],
                   "answerable": True})
    st = _state("PF ceiling for <NAME_1> in September?")
    d = drafter.draft(st, Retriever(CHUNKS, RULES).search("PF ceiling", "IN", date(2026, 9, 1)), [], date(2026, 9, 1), m)
    assert d["mode"] == "model" and "<NAME_1>" in m.calls[0][1] and "R-IN-PF-2026-08#rule" in m.calls[0][1]


def test_model_not_answerable_or_over_budget_falls_back_to_facts_or_template():
    hits = Retriever(CHUNKS, RULES).search("PF ceiling", "IN", date(2026, 9, 1))
    st = _state("PF ceiling in September?")
    facts = tools.run_tools(st, Retriever(CHUNKS, RULES).rules, date(2026, 9, 1), None)
    no = FakeModel({"reply": "x", "answerable": False})
    assert drafter.draft(st, hits, facts, date(2026, 9, 1), no)["mode"] == "fallback"
    assert drafter.draft(_state("random words here"), [], [], date(2026, 9, 1), no) is None
    d = drafter.draft(st, hits, facts, date(2026, 9, 1), FakeModel(exc=BudgetExceeded("cap")))
    assert d["mode"] == "fallback" and "INR 25,000" in d["reply"]


def test_howto_question_gets_the_matching_guide():
    chunks = [*CHUNKS, {"chunk_id": "KB-0105#title", "kb_id": "KB-0105", "source_kind": "kb_title", "region": "ALL",
                        "topic": "payslip", "title": "Downloading payslips in bulk",
                        "content": "KB-0105: Downloading payslips in bulk"}]
    r = Retriever(chunks, RULES)
    st = _state("how to see my payslip?")
    d = drafter.draft(st, r.search(st["body"], "IN", date(2026, 9, 1)), [], date(2026, 9, 1))
    assert d and "KB-0105" in d["reply"] and d["citations"] == ["KB-0105#title"]


def _deps(store, model=None):
    return Deps(store, MemoryVault(), b"k", retriever=Retriever(CHUNKS, RULES), model=model)


TENANTS = {"C-1001": {"tenant_id": "C-1001", "region": "IN", "tier": "Enterprise"}}


def test_statutory_ticket_is_drafted_from_sources_guarded_and_waits_for_review():
    store = MemoryAgentStore(TENANTS)
    tid = store.create("C-1001", "chat", "What is the PF wage ceiling for September 2026? EPF contribution query", None)
    state = run(tid, _deps(store), MemoryCheckpoints())
    assert state["route"] == "review" and state["draft_mode"] == "fallback", state.get("route_reason")
    assert state["guard"]["ok"], state["guard"]
    task = store.list_reviews()[0]
    assert "INR 25,000 per month" in task["draft"] and store.replies(tid) == []  # nothing sent before approval


def test_a_draft_that_fails_the_guard_goes_to_review_not_to_the_customer():
    store = MemoryAgentStore(TENANTS)
    bad = FakeModel({"reply": "Guaranteed: INR 99,999 [R-IN-PF-2026-08#rule]", "citations": [], "answerable": True})
    tid = store.create("C-1001", "chat", "How do I add a new employee?", None)
    state = run(tid, _deps(store, bad), MemoryCheckpoints())
    if state["draft_mode"] == "model":
        assert not state["guard"]["ok"] and store.replies(tid) == []
        assert "output guard" in store.list_reviews()[0]["route_reason"]
    else:  # How-To with no facts: template acknowledgement, sent
        assert state["sent"]


def test_customer_view_never_shows_tokens():
    assert customer_view("Hi <NAME_1>, we emailed <EMAIL_1>.") == "Hi, we emailed your email."
    assert customer_view("Hi <NAME_1>", reveal=lambda t: "Kavya") == "Hi Kavya"
    assert customer_view("PAN <PAN_1> noted") == "PAN the details you shared noted"


def test_state_with_sources_is_json_serialisable():
    store = MemoryAgentStore(TENANTS)
    tid = store.create("C-1001", "chat", "What is the PF wage ceiling for September 2026?", None)
    state = run(tid, _deps(store), MemoryCheckpoints())
    json.dumps({k: v for k, v in state.items() if k != "meta"})


@pytest.mark.parametrize("text,kind", [
    ("hi", "greeting"), ("Hello!", "greeting"), ("नमस्ते", "greeting"), ("مرحبا", "greeting"),
    ("thanks", "thanks"), ("ok thanks", "thanks"), ("payment delayed", "vague"), ("help", "vague"),
    ("how to see my payslip?", None), ("PF issue", None), ("run PR-202609 stuck", None),
])
def test_conversation_kind(text, kind):
    from agent.conversation import kind as k

    assert k(text) == kind


@pytest.mark.parametrize("text,route,phrase", [
    ("hi", "chat", "Payce Support assistant"),
    ("payment delayed", "ask", "which payroll month"),
])
def test_chat_greets_and_asks_instead_of_opening_a_ticket(text, route, phrase):
    store = MemoryAgentStore(TENANTS)
    tid = store.create("C-1001", "chat", text, None)
    state = run(tid, _deps(store), MemoryCheckpoints())
    assert state["route"] == route and state["sent"]
    reply = store.replies(tid)[0]["body"]
    assert phrase in reply and "is with our" not in reply


@pytest.mark.parametrize("text,lang", [
    ("كيف يمكنني تحميل كشوف الرواتب لجميع الموظفين دفعة واحدة؟", "ar"),
    ("सभी कर्मचारियों की पेस्लिप कैसे डाउनलोड करें?", "hi"),
])
def test_arabic_and_hindi_questions_find_the_english_guide_and_answer_in_their_language(text, lang):
    from agent import guard

    chunks = [*CHUNKS, {"chunk_id": "KB-0105#title", "kb_id": "KB-0105", "source_kind": "kb_title", "region": "ALL",
                        "topic": "payslip", "title": "Downloading payslips in bulk",
                        "content": "KB-0105: Downloading payslips in bulk"}]
    r = Retriever(chunks, RULES)
    hits = r.search(text, "UAE", date(2026, 9, 1))
    assert hits and hits[0]["chunk_id"] == "KB-0105#title"
    st = {**_state(text, "UAE"), "language": lang}
    d = drafter.draft(st, hits, [], date(2026, 9, 1))
    g = guard.check(d["reply"], ticket_text=text, region="UAE", language=lang, hits=hits, facts=[],
                    as_of=date(2026, 9, 1), ref="PN-1")
    assert g["ok"], g
