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


def _ask(conf, layers):
    store = MemoryAgentStore(TENANTS)
    deps = Deps(store, MemoryVault(), b"k", retriever=Retriever([*CHUNKS, PAYSLIP, PAYSLIP_STEPS], RULES),
                classifier=Clf(conf, layers))
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
