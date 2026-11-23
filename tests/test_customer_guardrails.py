"""Customer replies: specific steps only, nothing internal, and no agent answer sent below 0.8 confidence."""
from agent import drafter, guard
from agent.nodes import Deps
from agent.retrieval import Retriever
from agent.runner import MemoryCheckpoints, run
from agent.store import MemoryAgentStore
from intake.vault import MemoryVault
from tests.test_drafting import CHUNKS, PAYSLIP, PAYSLIP_STEPS, RULES, TENANTS

Q = "How do I download payslips for all employees?"


def _check(text, howto=True, lang="en"):
    return guard.check(text, ticket_text=Q, region="IN", language=lang, ref="PN-1", howto=howto)["problems"]


def test_internal_details_never_reach_the_customer():
    for leak in ("See KB-0105 for this.", "This guide has solved 39 similar questions.",
                 "My confidence is 0.5.", "Rule R11-howto applies.", "Found in the answer cache.",
                 "Write to [email removed] for help.", "The language model thinks so."):
        assert "internal_detail" in _check("1. Open Payroll > Payslips.\n2. Choose Download as ZIP. " + leak), leak
    assert "internal_detail" not in _check("1. Open Payroll > Payslips.\n2. Choose Download as ZIP.")


def test_a_howto_answer_must_be_specific_steps():
    assert "not_specific" in _check("The guide for this is “Downloading payslips in bulk”. "
                                     "Which part are you stuck on?")
    assert "not_specific" not in _check("1. Open Payroll > Payslips.\n2. Select all employees, then Download as ZIP.")
    assert "not_specific" not in _check("Thanks, I've passed this on.", howto=False)  # acknowledgements are not answers


def test_masked_contact_lines_are_dropped_from_steps_but_the_steps_stay():
    out = drafter.customer_steps("1. Open Payroll > Payslips.\n2. Click Reset. Mail [email removed] if stuck.\n"
                                 "Questions? Call [phone removed].")
    assert out == "1. Open Payroll > Payslips.\n2. Click Reset."


class Clf:
    def __init__(self, conf, layers):
        self.conf, self.layers = conf, layers

    def classify(self, text, ticket_id=None):
        return {"team": "How-To", "confidence": self.conf, "branch": "auto", "second": None, "layers": self.layers}


def _ask(conf, layers, guide_at=99.0):
    # guide_at 99: the guide-match path is switched off, so these test the classifier gate alone
    store = MemoryAgentStore(TENANTS)
    deps = Deps(store, MemoryVault(), b"k", retriever=Retriever([*CHUNKS, PAYSLIP, PAYSLIP_STEPS], RULES),
                classifier=Clf(conf, layers), guide_at=guide_at)
    tid = store.create("C-1001", "chat", Q, None)
    store.save_progress(tid, conversation_id="conv-g0000001")
    return store, tid, run(tid, deps, MemoryCheckpoints())


def test_confident_and_agreeing_answer_is_sent():
    store, tid, st = _ask(0.9, {"keywords": "How-To", "similar": "How-To"})
    assert st["sent"] and "Download as ZIP" in store.replies(tid)[0]["body"]


def test_answer_below_0_8_waits_for_a_person():
    store, tid, st = _ask(0.6, {"keywords": "How-To", "similar": "How-To"})
    assert not st.get("sent") and not store.replies(tid)
    t = store.tickets[tid]
    assert t["agent_status"] == "waiting_review" and "confidence 0.60 is below 0.80" in t["route_reason"]


def test_answer_waits_when_the_classifiers_disagree_even_if_confident():
    store, tid, st = _ask(0.9, {"keywords": "How-To", "similar": "Payroll"})
    assert not st.get("sent") and "classifiers disagreed" in store.tickets[tid]["route_reason"]


GUIDE_URL = "https://help.payce.example/payslips/bulk-download"


def test_a_guide_link_is_given_and_only_that_link_is_allowed():
    titled = {**PAYSLIP, "url": GUIDE_URL}
    hits = [titled]
    ok = guard.check(f"Here is the Payce guide with the steps: “Downloading payslips in bulk” {GUIDE_URL} "
                     "[KB-0105#title]", ticket_text=Q, region="IN", language="en", hits=hits, ref="PN-1", howto=True)
    assert ok["ok"], ok  # a link to the guide's own page is specific
    bad = guard.check("See https://evil.example/login for the steps.\n1. a\n2. b", ticket_text=Q, region="IN",
                      language="en", hits=hits, ref="PN-1", howto=True)
    assert "unknown_link" in bad["problems"]


def test_hinglish_question_with_a_guide_link_gets_the_link_in_hinglish():
    arts = Retriever([{**PAYSLIP, "url": GUIDE_URL}], []).howto_articles("download payslips in bulk for all employees",
                                                                       "IN", None)
    d = drafter.draft_howto({"ticket_id": "t" * 32, "body": "kaise download karun slip?", "language": "hi-Latn"}, arts)
    assert d and GUIDE_URL in d["reply"] and "Iske steps" in d["reply"]


def test_import_rejects_a_link_that_is_not_plain_https(monkeypatch):
    import pytest

    from agent import knowledge_import as ki
    from shared import settings

    with pytest.raises(ValueError, match="https"):
        ki.guide_url("x.md", "http://help.payce.example/a")
    monkeypatch.setattr(settings, "HELP_DOMAINS", {"help.payce.example"})
    assert ki.guide_url("x.md", GUIDE_URL) == GUIDE_URL
    with pytest.raises(ValueError, match="HELP_DOMAINS"):
        ki.guide_url("x.md", "https://elsewhere.example/a")


def test_hinglish_is_recognised():
    from loader.normalize import language

    assert language("kaise download karun slip?") == "hi-Latn" and language("kahan se khulegi ye guide?") == "hi-Latn"
    assert language("Where is the PF report for Ki and Ka teams?") == "en"


def test_an_information_question_with_a_strong_guide_match_is_answered_even_at_0_6():
    store, tid, st = _ask(0.6, {"keywords": "How-To", "similar": "Payroll"}, guide_at=5.0)
    assert st["sent"] and "Download as ZIP" in store.replies(tid)[0]["body"]


# ---- risk policy: money and personal data always go to a person ------------------------------------------

def _risk(text, tenant="C-1001"):
    from agent.runner import MemoryCheckpoints as CP

    store = MemoryAgentStore(TENANTS)
    deps = Deps(store, MemoryVault(), b"k", retriever=Retriever([*CHUNKS, PAYSLIP, PAYSLIP_STEPS], RULES))
    tid = store.create(tenant, "chat", text, None)
    store.save_progress(tid, conversation_id="conv-r0000001")
    st = run(tid, deps, CP())
    return store, tid, st


def test_refund_below_the_limit_goes_to_a_payroll_specialist():
    store, tid, st = _risk("Please refund INR 85,000 that was deducted twice in March")
    assert st["route_rule"] == "R06d-money" and st["queue"] == "Payroll-L2"
    body = store.replies(tid)[0]["body"]
    assert "can't approve or move money" in body and "INR 85,000" in body and "finance lead" not in body
    assert store.tickets[tid]["agent_status"] == "waiting_review"
    assert [t["kind"] for t in store.list_reviews() if t["ticket_id"] == tid] == ["reply"]


def test_refund_above_the_limit_needs_a_finance_lead_too():
    store, tid, st = _risk("approve my refund of 2 lakh please")
    assert st["route_rule"] == "R06b-money-second-approver" and st["queue"] == "Finance-Approvals"
    body = store.replies(tid)[0]["body"]
    assert "finance lead" in body and "(2 lakh)" in body  # the customer's words in the reply
    assert "INR 200,000" in st["route_reason"]  # the normalised amount for the approver


def test_another_employees_salary_goes_to_the_privacy_desk():
    store, tid, st = _risk("Send me the salary of Rahul Sharma for March")
    assert st["route_rule"] == "R06e-private-data" and st["queue"] == "Privacy-Desk"
    assert "privacy team" in store.replies(tid)[0]["body"]


def test_salary_not_credited_is_p1_for_a_person_and_legal_threats_go_to_the_lead():
    _, _, st = _risk("Salary not credited to 3 employees this month, bank shows failed")
    assert st["route_rule"] == "R08b-pay-at-risk" and "P1" in st["route_reason"]
    store, tid, st = _risk("If this is not fixed we will take legal action")
    assert st["route_rule"] == "R06a-legal" and "support lead" in store.replies(tid)[0]["body"]


def test_risk_replies_pass_the_guard_in_every_language():
    from agent import templates

    for kind in ("money", "money_high", "private", "legal"):
        for lang in ("en", "hi-Latn", "hi", "ar"):
            text = templates.render(kind, lang, ref="PN-1", amount=" (INR 85,000)")
            g = guard.check(text, ticket_text="refund INR 85,000", region="IN", language=lang, ref="PN-1")
            assert g["ok"], (kind, lang, g)


def test_demo_guides_load_once_and_never_overwrite_a_real_article():
    from agent import knowledge_import as ki

    store = MemoryAgentStore(TENANTS)
    real = ki.parse_article("x.md", "---\nid: KB-0105\ntitle: Downloading payslips in bulk\n---\n1. Real step one.\n2. Real step two.")
    store.import_articles([real])
    added = ki.demo_guides(store)
    assert len(added) >= 10 and "KB-0105" not in {a["kb_id"] for a in added}
    assert ki.demo_guides(store) == []  # idempotent
    steps = [c["content"] for c in store.knowledge()[0] if c["kb_id"] == "KB-0105" and c["source_kind"] == "kb_article"]
    assert steps and "Real step one" in steps[0]


# ---- what a reviewer writes is kept and reused ------------------------------------------------------------

def _learning():
    store = MemoryAgentStore(TENANTS)
    store.kb = [*CHUNKS, PAYSLIP]  # the guide has a title only: the first askers go to a person
    deps = Deps(store, MemoryVault(), b"k", retriever=Retriever(store.knowledge()[0], RULES), answer_at=0.5)

    def ask(q, cid):
        tid = store.create("C-1001", "chat", q, None)
        store.save_progress(tid, conversation_id=cid)
        return tid, run(tid, deps, MemoryCheckpoints())
    return store, deps, ask


STEPS = "1. Go to Payroll > Payslips.\n2. Pick the month, select all employees and click Download as ZIP."


def test_an_empty_approval_is_refused_so_no_customer_gets_an_empty_message():
    import pytest

    store, _, ask = _learning()
    ask("How do I download payslips for all employees?", "conv-l0000001")
    ask("how can I download the payslips of all my employees", "conv-l0000002")
    reply = next(t for t in store.list_reviews() if t["kind"] == "reply")
    with pytest.raises(ValueError, match="write the reply"):
        store.decide_review(reply["id"], "approve", None, "arvind")


def test_steps_written_once_answer_every_waiting_customer_and_every_later_asker():
    store, deps, ask = _learning()
    t1, _ = ask("How do I download payslips for all employees?", "conv-l0000003")
    t2, _ = ask("how can I download the payslips of all my employees", "conv-l0000004")
    task = next(t for t in store.list_reviews() if t["kind"] == "knowledge")
    store.decide_review(task["id"], "approve", STEPS, "arvind")
    for t in (t1, t2):  # both customers waiting on the question get the steps now
        assert store.replies(t)[-1]["body"] == STEPS and store.tickets[t]["agent_status"] == "replied"
    assert not store.list_reviews()  # the second customer's task was closed with the same answer
    # the answer is now part of the guide, so retrieval finds it for other wordings (worker reloads)
    assert any(c["chunk_id"].startswith("KB-0105#approved-") for c in store.knowledge()[0])
    deps.retriever = Retriever(store.knowledge()[0], RULES)
    t3, st = ask("can I download the payslips of all my employees together?", "conv-l0000005")
    assert st["sent"] and "Download as ZIP" in store.replies(t3)[0]["body"]


def test_a_reply_a_reviewer_writes_for_a_howto_ticket_is_learned_too():
    store, _, ask = _learning()
    ask("How do I download payslips for all employees?", "conv-l0000006")
    t2, _ = ask("how can I download the payslips of all my employees", "conv-l0000007")
    reply = next(t for t in store.list_reviews() if t["kind"] == "reply")
    store.decide_review(reply["id"], "approve", STEPS, "arvind")
    assert store.replies(t2)[-1]["body"] == STEPS
    assert any(e["answer"] == STEPS for e in store.library)


def test_a_problem_report_is_never_answered_with_a_setup_guide():
    # Q3: "webhook not firing" got the integration setup guide and counted as resolved; it needs a person
    from agent import conversation

    for text in ("Webhook not firing on payroll completion", "API token returns 401 since yesterday",
                 "Arrears not included. Please advise how to add them", "Salary register export is blank"):
        assert conversation.PROBLEM.search(text) and not conversation.is_howto(text), text


def test_a_guide_is_used_only_when_its_own_words_fit():
    from agent.nodes import clear_winner

    right = [{"has_steps": True, "score": 12.3, "own_score": 9.3}, {"score": 6.3}]
    only_past_questions = [{"has_steps": True, "score": 14.0, "own_score": 0.0}, {"score": 5.6}]
    too_close = [{"has_steps": True, "score": 14.0, "own_score": 6.0}, {"score": 13.3}]
    assert clear_winner(right, 5.0) and not clear_winner(only_past_questions, 5.0) and not clear_winner(too_close, 5.0)
