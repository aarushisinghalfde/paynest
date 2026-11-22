"""The Bedrock provider: same json_call, ledger and budget as OpenRouter, Converse underneath."""
import pytest

from agent import models
from agent.models import BudgetExceeded, MemoryLedger, ModelClient, ModelError

CFG = {"provider": "bedrock", "budget": {"daily_usd_cap": 0.5},
       "providers": {"bedrock": {"region": "ap-southeast-2",
                                 "ladder": ["apac.amazon.nova-micro-v1:0", "apac.amazon.nova-pro-v1:0"],
                                 "prices": {"apac.amazon.nova-pro-v1:0": {"in": 0.8, "out": 3.2}}}}}


@pytest.fixture
def bedrock(monkeypatch):
    monkeypatch.setattr(models, "config", lambda: CFG)


def _converse(text, tin=1000, tout=500):
    calls = []

    def call(model, system, user, max_tokens):
        calls.append({"model": model, "system": system, "user": user})
        return {"output": {"message": {"content": [{"text": text}]}}, "usage": {"inputTokens": tin, "outputTokens": tout}}

    return call, calls


def test_converse_reply_is_parsed_costed_and_ledgered(bedrock):
    call, calls = _converse('Sure: {"team": "Payroll", "confidence": 0.9}')
    led = MemoryLedger()
    c = ModelClient(ledger=led, transport=call)
    assert c.key == "iam"  # no API key: the IAM role signs the calls
    r = c.json_call("sys", "masked <NAME_1> text", rung=1, purpose="draft")
    assert r.data["team"] == "Payroll" and r.model == "apac.amazon.nova-pro-v1:0"
    assert r.cost_usd == pytest.approx(0.8 + 1.6) and led.rows[0]["tokens_in"] == 1000
    assert calls[0]["user"] == "masked <NAME_1> text"


def test_errors_and_budget_behave_like_openrouter(bedrock):
    def boom(**kw):
        raise RuntimeError("Operation not allowed")

    with pytest.raises(ModelError):
        ModelClient(transport=boom).json_call("s", "u")
    call, _ = _converse("no json here")
    with pytest.raises(ModelError):
        ModelClient(transport=call).json_call("s", "u")
    led = MemoryLedger()
    led.record(cost_usd=1.0)
    with pytest.raises(BudgetExceeded):
        ModelClient(ledger=led, transport=call).json_call("s", "u")
