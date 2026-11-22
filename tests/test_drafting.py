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
    assert customer_view("See the guide (KB-0105) [KB-0105#title]. Run is done [payroll-api:PR-1].") == (
        "See the guide (KB-0105). Run is done.")


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


def _chat(store, deps, text, cid="conv-1234"):
    tid = store.create("C-1001", "chat", text, None)
    store.save_progress(tid, conversation_id=cid)
    return tid, run(tid, deps, MemoryCheckpoints())


PAYSLIP = {"chunk_id": "KB-0105#title", "kb_id": "KB-0105", "source_kind": "kb_title", "region": "ALL",
           "topic": "payslip", "title": "Downloading payslips in bulk", "content": "KB-0105: Downloading payslips in bulk"}


def test_howto_flow_answers_from_rag_then_from_the_cache():
    from agent.answer_cache import MemoryAnswerCache

    store, cache = MemoryAgentStore(TENANTS), MemoryAnswerCache()
    deps = Deps(store, MemoryVault(), b"k", retriever=Retriever([*CHUNKS, PAYSLIP], RULES), answer_cache=cache)
    _, first = _chat(store, deps, "How do I download payslips for all employees?")
    assert first["team"] == "How-To" and first["draft_mode"] == "fallback" and first["sent"]
    t2, second = _chat(store, deps, "how can I download the payslips of all my employees", cid="conv-other")
    assert second["draft_mode"] == "cache" and second["guard"]["ok"] and second["sent"]
    assert "KB-0105" in store.replies(t2)[0]["body"] and "How-To cache" in store.tickets[t2]["route_reason"]
    _, other = _chat(store, deps, "How do I add a new employee?", cid="conv-3")
    assert other["draft_mode"] != "cache"  # a different question is not served from the cache


def test_follow_up_is_read_with_the_earlier_turn():
    store = MemoryAgentStore(TENANTS)
    deps = _deps(store)
    _, first = _chat(store, deps, "payment delayed")
    assert first["route"] == "ask"
    _, second = _chat(store, deps, "salary for September, 12 employees, bank shows pending")
    assert second["context"] == store.tickets[first["ticket_id"]]["masked_body"]
    assert second["route"] != "ask" and second["history"][0]["reply"]


def test_how_to_reply_never_quotes_a_statutory_figure():
    store = MemoryAgentStore(TENANTS)
    _, st = _chat(store, _deps(store), "How do I download the payslips for September 2026?")
    assert st["route"] == "reply"
    assert "25,000" not in (st.get("draft") or "") and not any(f["tool"] == "get_rate" for f in st["sources"]["facts"])
    # asking for the figure itself, even worded as a how-to, goes to Statutory and a person (phase C eval)
    _, st = _chat(store, _deps(store), "How do I see the PF wage ceiling for September 2026?", cid="conv-5678")
    assert st["team"] == "Statutory" and st["route"] == "review" and not st.get("sent")


def test_is_howto():
    from agent.conversation import is_howto

    assert is_howto("How do I download payslips?") and is_howto("كيف يمكنني تحميل كشوف الرواتب")
    assert not is_howto("How do I fix the rejected WPS file?") and not is_howto("Salary not credited")


def test_repeated_howto_questions_never_open_an_incident():
    from agent.answer_cache import MemoryAnswerCache

    store = MemoryAgentStore(TENANTS)
    deps = Deps(store, MemoryVault(), b"k", retriever=Retriever([*CHUNKS, PAYSLIP], RULES), answer_cache=MemoryAnswerCache())
    from datetime import UTC, datetime

    for i in range(7):
        tid = store.create("C-1001", "chat", "How do I download payslips for all employees?", None)
        store.save_progress(tid, conversation_id=f"conv-{i:04d}x", created_at=datetime.now(UTC))
        st = run(tid, deps, MemoryCheckpoints())
        assert st["route"] == "reply" and not st.get("incident_id"), (i, st["route"], st.get("route_reason"))
    # the same burst of a real problem still opens an incident
    for _ in range(5):
        tid = store.create("C-1001", "chat", "Salary not credited for our employees, bank shows pending", None)
        store.save_progress(tid, created_at=datetime.now(UTC))
        st = run(tid, deps, MemoryCheckpoints())
    assert st.get("incident_id") and st["route"] == "incident"


def test_vague_message_after_an_answered_question_still_gets_its_own_question():
    store = MemoryAgentStore(TENANTS)
    deps = Deps(store, MemoryVault(), b"k", retriever=Retriever([*CHUNKS, PAYSLIP], RULES))
    _chat(store, deps, "How do I download payslips for all employees?")
    _, st = _chat(store, deps, "payment delayed")
    assert st["route"] == "ask" and not st.get("context")


def test_a_full_question_is_not_joined_to_the_previous_turn_but_a_follow_up_is():
    from agent.conversation import is_follow_up

    store = MemoryAgentStore(TENANTS)
    deps = _deps(store)
    _chat(store, deps, "How do I add a new employee?")
    _, st = _chat(store, deps, "What is the status of payroll run PR-202609?")
    assert not st.get("context")
    assert is_follow_up("and for contractors?") and is_follow_up("aur UAE ke liye?")
    assert not is_follow_up("What is the status of payroll run PR-202609?")


def test_problem_reports_are_not_offered_an_unrelated_guide():
    store = MemoryAgentStore(TENANTS)
    _, st = _chat(store, _deps(store), "September salary for 12 employees, bank shows pending")
    assert st["draft_mode"] == "template" and st["sources"]["hits"] == []


def test_update_request_while_waiting_for_review_gets_a_status_reply():
    store = MemoryAgentStore(TENANTS)
    deps = _deps(store)
    t1, first = _chat(store, deps, "What is the PF wage ceiling for September 2026 payroll?")
    assert first["route"] == "review"
    t2, st = _chat(store, deps, "update?")
    assert st["route"] == "chat" and st["sent"] and not store.list_reviews()[1:]  # no second review task
    reply = store.replies(t2)[0]["body"]
    assert t1[:8] in reply and "payroll specialist" in reply


# ---- How-To agent: library -> cache -> RAG (with past resolutions) -> learning loop ----------------

ONBOARD = {"chunk_id": "KB-0102#title", "kb_id": "KB-0102", "source_kind": "kb_title", "region": "ALL",
           "topic": "howto_onboard", "title": "Adding a new employee (single and bulk upload)",
           "content": "KB-0102: Adding a new employee (single and bulk upload)"}
EXAMPLES = [{"question": "We want only HR heads to see CTC. How to set role permissions?", "kb_id": "KB-0102"},
            {"question": "How do I restrict who sees salary data?", "kb_id": "KB-0102"},
            {"question": "Restrict salary visibility to HR heads only", "kb_id": "KB-0102"}]


def _howto_deps(store, cache=None):
    return Deps(store, MemoryVault(), b"k", retriever=Retriever([*CHUNKS, PAYSLIP, ONBOARD], RULES, examples=EXAMPLES),
                answer_cache=cache)


def test_past_resolutions_find_the_guide_the_title_alone_would_miss():
    r = Retriever([*CHUNKS, PAYSLIP, ONBOARD], RULES, examples=EXAMPLES)
    q = "how can I make salary data visible only to HR heads?"
    top = r.howto_articles(q, "IN", date(2026, 9, 1))[0]
    assert top["chunk_id"] == "KB-0102#title" and top["solved"] >= 2
    without = Retriever([*CHUNKS, PAYSLIP, ONBOARD], RULES).howto_articles(q, "IN", date(2026, 9, 1))
    assert not without or without[0]["chunk_id"] != "KB-0102#title" or without[0]["score"] < top["score"]


def test_learning_loop_support_writes_once_then_every_similar_question_gets_the_steps():
    store = MemoryAgentStore(TENANTS)
    deps = _howto_deps(store)
    t1, first = _chat(store, deps, "How do I download payslips for all employees?", cid="conv-a1b2c3d4")
    assert first["draft_mode"] == "fallback" and "KB-0105" in store.replies(t1)[0]["body"]
    task = next(t for t in store.list_reviews() if t["kind"] == "knowledge")
    with pytest.raises(ValueError):
        store.decide_review(task["id"], "approve", "")  # an answer must be written
    steps = "Go to Payroll > Payslips, pick the month, select all employees and choose Download as ZIP."
    store.decide_review(task["id"], "approve", steps, "arvind")
    assert store.replies(t1)[-1]["body"] == steps  # the first customer gets the steps too
    t2, second = _chat(store, deps, "how can I download the payslips of all my employees", cid="conv-e5f6a7b8")
    assert second["draft_mode"] == "library" and second["guard"]["ok"] and second["sent"]
    assert customer_view(store.replies(t2)[0]["body"]) == steps
    assert "approved How-To answers" in store.tickets[t2]["route_reason"]
    assert not [t for t in store.list_reviews() if t["kind"] == "knowledge"]  # nothing new to write


def test_one_knowledge_task_per_question_not_one_per_customer():
    store = MemoryAgentStore(TENANTS)
    deps = _howto_deps(store)
    _chat(store, deps, "How do I download payslips for all employees?", cid="conv-11111111")
    _chat(store, deps, "how can I download the payslips of all my employees", cid="conv-22222222")
    assert len([t for t in store.list_reviews() if t["kind"] == "knowledge"]) == 1


def test_stuck_after_the_guide_hands_over_to_a_teammate_with_the_conversation():
    store = MemoryAgentStore(TENANTS)
    deps = _howto_deps(store)
    _chat(store, deps, "How do I download payslips for all employees?", cid="conv-33333333")
    t2, st = _chat(store, deps, "I can't find the bulk download option anywhere", cid="conv-33333333")
    assert st["context_team"] == "How-To" and st["team"] == "How-To"
    assert "passed this to our How-To team" in store.replies(t2)[0]["body"]
