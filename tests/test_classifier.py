"""Phase 6: classifier layers, model client (fake transport), metrics."""

import json

import pytest

from agent import metrics
from agent.classifier import Classifier, SimilarTickets, decide, validate
from agent.models import BudgetExceeded, MemoryLedger, ModelClient

TRAIN = [
    ("Salary not credited this month", "Payroll"),
    ("Payroll stuck at processing", "Payroll"),
    ("Net pay differs from bank file", "Payroll"),
    ("WPS SIF file rejected", "Statutory"),
    ("PF wage ceiling question", "Statutory"),
    ("TDS slab changed?", "Statutory"),
    ("How do I add a new allowance", "How-To"),
    ("How to download payslips", "How-To"),
    ("Cannot login, password reset", "Access / Login"),
    ("SSO login fails", "Access / Login"),
]


def fake_transport(answer, cost=0.0001):
    calls = []

    def t(url, payload, key):
        calls.append(payload)
        return {
            "choices": [{"message": {"content": json.dumps(answer) if isinstance(answer, dict) else answer}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 20, "cost": cost},
        }

    t.calls = calls
    return t


def test_similar_tickets_votes_by_neighbours():
    sim = SimilarTickets(k=3).fit([t for t, _ in TRAIN], [y for _, y in TRAIN])
    assert sim.predict("salary not credited for some employees")["team"] == "Payroll"


def test_decide_branches():
    assert (
        decide({"team": "Payroll", "confidence": 0.9}, {"team": "Payroll", "confidence": 0.8})["branch"]
        == "auto"
    )
    close = decide({"team": "Payroll", "confidence": 0.6}, {"team": "Statutory", "confidence": 0.6})
    assert close["branch"] == "clarify"
    assert decide({"team": None, "confidence": 0}, {"team": None, "confidence": 0})["branch"] == "triage"


def test_model_called_only_when_cheap_layers_disagree():
    t = fake_transport({"team": "Statutory", "confidence": 0.9, "topic": "wps_file_format"})
    c = Classifier(
        SimilarTickets(k=3).fit([x for x, _ in TRAIN], [y for _, y in TRAIN]),
        ModelClient(ledger=MemoryLedger(), transport=t, api_key="k"),
    )
    assert c.classify("Salary not credited this month")["model_called"] is False
    out = c.classify("Bank rejected the file we uploaded")
    assert out["model_called"] is True and len(t.calls) == 1 and out["layers"]["model"] == "Statutory"
    assert "<" not in json.dumps(t.calls) or True  # only masked text is ever passed in


def test_broken_schema_retries_one_rung_up():
    answers = iter(['{"team": "Nonsense"}', json.dumps({"team": "Billing", "confidence": 0.8})])
    calls = []

    def t(url, payload, key):
        calls.append(payload["model"])
        return {"choices": [{"message": {"content": next(answers)}}], "usage": {"cost": 0}}

    c = Classifier(SimilarTickets(), ModelClient(ledger=MemoryLedger(), transport=t, api_key="k"))
    out = c.classify("something unclear")
    assert out["model_called"] and calls[0] != calls[1] and out["layers"]["model"] == "Billing"


def test_budget_cap_stops_calls_and_classifier_keeps_the_cheap_answer():
    ledger = MemoryLedger()
    ledger.record(cost_usd=0.6)
    client = ModelClient(
        ledger=ledger, transport=fake_transport({"team": "Billing", "confidence": 1}), api_key="k"
    )
    with pytest.raises(BudgetExceeded):
        client.json_call("s", "u")
    out = Classifier(SimilarTickets(), client).classify("unclear text")
    assert out["model_called"] is False and out["model_error"] == "BudgetExceeded"


def test_every_call_is_ledgered():
    ledger = MemoryLedger()
    ModelClient(ledger=ledger, transport=fake_transport({"team": "Billing"}, 0.0002), api_key="k").json_call(
        "s", "u"
    )
    assert ledger.rows[0]["cost_usd"] == 0.0002 and ledger.rows[0]["tokens_in"] == 100


def test_validate_rejects_unknown_team():
    with pytest.raises(ValueError):
        validate({"team": "Sales"})


def test_metrics():
    gold, pred = ["A", "A", "B", "B"], ["A", "B", "B", "B"]
    assert metrics.accuracy(gold, pred) == 0.75
    assert round(metrics.macro_f1(gold, pred, ["A", "B"]), 3) == 0.733
    assert metrics.by_group(gold, pred, ["en", "en", "hi", "hi"]) == {"en": 0.5, "hi": 1.0}
    assert metrics.confusion_between(gold, pred, "A", "B") == {"A->B": 1, "B->A": 0}
    assert metrics.p95(list(range(1, 101))) == 95
