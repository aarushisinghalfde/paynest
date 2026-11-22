"""Plan v2 phase C: fixes found by the labelled-set eval, and the eval's own scoring."""
from datetime import date

import pytest

from agent import conversation, drafter, guard, labelled_eval
from agent.classifier import decide


def test_near_copy_past_tickets_outweigh_a_single_keyword_on_a_tie():
    kw = {"team": "Statutory", "confidence": 1.0, "source": "keywords"}
    near = {"team": "Onboarding", "confidence": 1.0, "nearest_similarity": 0.98, "source": "similar"}
    far = {**near, "nearest_similarity": 0.3}
    assert decide(kw, near, auto_at=0.5)["team"] == "Onboarding"  # "statutory settings checklist": 39/39 Onboarding
    assert decide(kw, far, auto_at=0.5)["team"] == "Statutory"    # a new wording: keep the keywords


@pytest.mark.parametrize("text,want", [
    ("पीएफ की वेतन सीमा अभी कितनी है और गणना कैसे होगी?", True),
    ("كيف يتم احتساب مكافأة نهاية الخدمة للموظف الذي أكمل ٣ سنوات؟", True),
    ("What is the PF wage ceiling for September?", True),
    ("PF kitna katega is mahine?", True),
    ("How do I download the PF ECR file?", False),
    ("PF deduction alag aa raha hai", False),
    ("Can someone confirm the statutory settings checklist for our state?", False),
])
def test_statutory_figure_questions(text, want):
    assert conversation.asks_statutory_figure(text) is want


@pytest.mark.parametrize("lang", ["ar", "hi", "en"])
def test_fact_fallback_is_written_in_the_customers_script(lang):
    facts = [{"tool": "get_rate", "source": "R-AE-WPS-2026-07#rule", "title": "WPS SIF file format",
              "value": "SIF v3 (16 columns, new EDR layout)", "in_force_since": "2026-07-15"}]
    d = drafter.fallback([], facts, date(2026, 9, 3), "PN-1", lang)
    g = guard.check(d["reply"], ticket_text="", region="UAE", language=lang, facts=facts, ref="PN-1")
    assert g["ok"], (lang, g, d["reply"])


def _row(**kw):
    base = {"ref": "PN-1", "language": "en", "gold": "Payroll", "customer_pick": "Payroll", "pred": "Payroll",
            "branch": "auto", "route": "reply", "rule": "R99-default", "tier": "template", "sent": True,
            "guard_ok": True, "guard_problems": [], "sent_text": "Thanks", "masked": "salary late"}
    return {**base, **kw}


def test_eval_gates_catch_a_statutory_answer_sent_without_a_person_and_a_leak():
    rows = [_row(), _row(ref="PN-2", gold="Statutory", pred="Payroll", tier="fallback"),
            _row(ref="PN-3", sent_text="call me on 9876543210")]
    g = dict((n, ok) for n, ok, _ in labelled_eval.gates(labelled_eval.summarize(rows)))
    assert not g["statutory_never_auto"] and not g["sent_replies_clean"] and not g["classify_accuracy"]


def test_eval_gates_pass_on_a_clean_run():
    rows = [_row(ref=f"PN-{i}") for i in range(10)] + [_row(ref="PN-S", gold="Statutory", pred="Statutory",
                                                             route="review", sent=False, tier="fallback")]
    assert all(ok for _, ok, _ in labelled_eval.gates(labelled_eval.summarize(rows)))


# ---- C2 faithfulness --------------------------------------------------------------------------
from agent import faithfulness  # noqa: E402
from agent.models import Result  # noqa: E402


class Judge:
    def __init__(self, claims):
        self.claims = claims

    def json_call(self, system, user, **kw):
        self.user = user
        return Result({"claims": self.claims}, "judge", 1, 1, 1, 0.0, 1.0)


SRC = {"hits": [{"chunk_id": "R-IN-PF-2026-08#rule", "title": "PF ceiling", "content": "INR 25,000 per month from 2026-08-01"}],
       "facts": []}


def test_a_claim_counts_only_with_a_source_the_drafter_actually_had():
    j = Judge([{"claim": "The ceiling is INR 25,000", "supported": True, "source": "R-IN-PF-2026-08#rule"},
               {"claim": "It applies to contractors", "supported": True, "source": None},
               {"claim": "It was 15,000 before", "supported": True, "source": "KB-9999#x"}])
    r = faithfulness.judge("draft", SRC, j)
    assert r["claims"] == 3 and r["supported"] == 1 and len(r["unsupported"]) == 2
    assert "R-IN-PF-2026-08#rule" in j.user  # the judge sees exactly the drafter's sources
    s = faithfulness.summarize([r, None])
    assert s["drafts_judged"] == 1 and s["score"] == round(1 / 3, 3)


def test_faithfulness_gate_appears_only_when_judged():
    ev = {"classification": {"accuracy": 1, "macro_f1": 1, "customer_pick": 0.9, "by_language": {"en": 1}},
          "statutory": {"n": 0, "answered_without_a_person": []}, "sent_dirty": [],
          "guard": {"drafts": 1, "passed": 1, "problems": {}}, "faithfulness": None}
    assert "faithfulness" not in [n for n, _, _ in labelled_eval.gates(ev)]
    ev["faithfulness"] = {"drafts_judged": 10, "claims": 20, "supported": 19, "score": 0.95, "examples_unsupported": []}
    assert dict((n, ok) for n, ok, _ in labelled_eval.gates(ev))["faithfulness"]
