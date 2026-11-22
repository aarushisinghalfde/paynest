"""Fixes from the v0.7.1 live chat check (3 fails out of 8)."""
from agent import drafter
from agent.models import Result
from agent.nodes import Deps, classify
from agent.retrieval import Retriever
from agent.runner import MemoryCheckpoints, run
from agent.store import MemoryAgentStore
from agent.unmask import customer_view
from intake.vault import MemoryVault
from tests.test_drafting import CHUNKS, RULES

PAYSLIP = {"chunk_id": "KB-0105#title", "kb_id": "KB-0105", "source_kind": "kb_title", "region": "ALL",
           "topic": "payslip", "title": "Downloading payslips in bulk", "content": "KB-0105: Downloading payslips in bulk"}
TENANTS = {"C-1001": {"tenant_id": "C-1001", "region": "IN", "tier": "Enterprise"},
           "C-1003": {"tenant_id": "C-1003", "region": "UAE", "tier": "Enterprise"}}


class FakeModel:
    def __init__(self, data):
        self.data = data

    def json_call(self, system, user, **kw):
        return Result(self.data, "m", 1, 10, 10, 0.0, 5.0)


class Unsure:
    """The live classifier: Payroll vs Statutory too close -> clarify (joint pod)."""

    auto_at = 0.5

    def classify(self, text, ticket_id=None):
        return {"team": "Statutory", "second": "Payroll", "confidence": 0.55, "branch": "clarify", "layers": {}}


def _chat(store, deps, tenant, text, cid):
    tid = store.create(tenant, "chat", text, None)
    store.save_progress(tid, conversation_id=cid)
    return tid, run(tid, deps, MemoryCheckpoints())


def test_model_reply_that_hides_the_guide_in_a_citation_still_names_it():
    # live: "You can download payslips in bulk using [KB-0105#title] guide." -> customer saw "using guide"
    m = FakeModel({"reply": "You can download payslips in bulk using [KB-0105#title] guide. Which pay run?",
                   "citations": ["KB-0105#title"], "answerable": False})
    arts = Retriever([PAYSLIP], []).howto_articles("download payslips all employees", "IN", None)
    d = drafter.draft_howto({"ticket_id": "t" * 32, "body": "How do I download payslips?", "language": "en"}, arts, m)
    shown = customer_view(d["reply"])
    assert "KB-0105" in shown and "Downloading payslips in bulk" in shown


def test_model_draft_that_fails_the_guard_is_replaced_by_the_fixed_wording_not_parked():
    # live: the Arabic How-To question got no reply (model draft failed the guard -> waiting for a person).
    # The fixed wording needs a confident guide match; English here, since one title alone scores an
    # Arabic question below GUIDE_MIN (the real data adds past questions in Arabic).
    bad = FakeModel({"reply": "Download them here [KB-9999#nope].", "citations": ["KB-9999#nope"], "answerable": True})
    store = MemoryAgentStore(TENANTS)
    deps = Deps(store, MemoryVault(), b"k", retriever=Retriever([*CHUNKS, PAYSLIP], RULES), model=bad)
    tid, st = _chat(store, deps, "C-1001", "How do I download payslips for all employees?", "conv-ar000001")
    assert st["sent"] and st["draft_mode"] == "fallback" and st["guard"]["replaced"]
    assert "KB-0105" in customer_view(store.replies(tid)[0]["body"])


def test_run_status_question_is_payroll_when_the_classifier_is_unsure():
    out = classify({"ticket_id": "t" * 32, "subject": "", "body": "What is the status of payroll run PR-202609?"},
                   Deps(None, None, b"k", classifier=Unsure()))
    assert out["team"] == "Payroll" and out["classification"]["branch"] == "auto"


def test_unsure_statutory_question_without_a_run_id_still_goes_to_the_pod():
    out = classify({"ticket_id": "t" * 32, "subject": "", "body": "Is PT deducted before or after the run?"},
                   Deps(None, None, b"k", classifier=Unsure()))
    assert out["classification"]["branch"] == "clarify"


def test_run_status_reply_without_an_inline_citation_is_sent_not_parked():
    # live v0.7.3: route reply, waiting_review, empty reply. The model put the citation only in the JSON list;
    # the run id is the customer's own number, so it is not an uncited claim.
    from agent import guard
    facts = [{"tool": "get_run_status", "source": "payroll-api:PR-202609", "run_id": "PR-202609",
              "status": "processing", "stage": "approval_pending"}]
    q = "What is the status of payroll run PR-202609?"
    ok = guard.check("Payroll run PR-202609 is processing, awaiting approval.", ticket_text=q, region="IN",
                     language="en", facts=facts, ref="x")
    assert ok["ok"], ok
    bad = guard.check("The PF ceiling is INR 25,000 per month.", ticket_text="PF ceiling?", region="IN",
                      language="en", ref="x")
    assert "uncited_answer" in bad["problems"]  # a figure the customer did not give still needs a source


def test_auto_reply_model_draft_failing_the_guard_falls_back_to_the_fixed_wording(monkeypatch):
    from agent import tools
    monkeypatch.setattr(tools, "run_tools", lambda *a, **k: [
        {"tool": "get_run_status", "source": "payroll-api:PR-202609", "run_id": "PR-202609",
         "status": "processing", "stage": "approval_pending"}])
    bad = FakeModel({"reply": "Run PR-202609 finishes on 30 November.", "citations": [], "answerable": True})
    store = MemoryAgentStore(TENANTS)
    deps = Deps(store, MemoryVault(), b"k", retriever=Retriever([*CHUNKS, PAYSLIP], RULES), model=bad,
                classifier=Unsure())
    tid, st = _chat(store, deps, "C-1001", "What is the status of payroll run PR-202609?", "conv-rs000001")
    assert st["sent"] and st["draft_mode"] == "fallback"
    assert "processing" in store.replies(tid)[0]["body"]
