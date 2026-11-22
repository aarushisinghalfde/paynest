"""Phase E: model steps on AgentCore - the provider on the app server and the runtime app."""
import pytest

from agent import models
from agent.models import MemoryLedger, ModelClient, ModelError

CFG = {"provider": "openrouter", "budget": {"daily_usd_cap": 0.5},
       "providers": {"openrouter": {"base_url": "x", "api_key_env": "NOPE", "ladder": ["m0", "m1"]},
                     "agentcore": {"region": "ap-southeast-2", "runtime_arn_env": "AGENTCORE_RUNTIME_ARN", "ladder": []}}}


@pytest.fixture
def cfg(monkeypatch):
    monkeypatch.setattr(models, "config", lambda: CFG)
    monkeypatch.setenv("AGENTCORE_RUNTIME_ARN", "arn:aws:bedrock-agentcore:ap-southeast-2:1:runtime/paynest-x")


def test_agentcore_provider_sends_masked_text_and_ledgers_the_runtime_cost(cfg):
    sent = []

    def runtime(payload):
        sent.append(payload)
        return {"data": {"team": "Payroll"}, "model": "m1", "rung": 1, "tokens_in": 10, "tokens_out": 5,
                "cost_usd": 0.0002, "ms": 300}

    led = MemoryLedger()
    c = ModelClient(ledger=led, transport=runtime, provider="agentcore")
    assert c.key == "iam"
    r = c.json_call("sys", "masked <NAME_1>", rung=1, purpose="draft")
    assert r.data == {"team": "Payroll"} and r.model == "agentcore:m1" and led.rows[0]["cost_usd"] == 0.0002
    assert sent[0] == {"system": "sys", "user": "masked <NAME_1>", "rung": 1, "purpose": "draft", "max_tokens": 400}


def test_agentcore_failures_fall_back_like_any_model_error(cfg, monkeypatch):
    def down(payload):
        raise ConnectionError("unreachable")

    with pytest.raises(ModelError):
        ModelClient(transport=down, provider="agentcore").json_call("s", "u")
    monkeypatch.delenv("AGENTCORE_RUNTIME_ARN")
    assert not ModelClient(provider="agentcore").key  # no runtime configured: callers skip the model


def test_runtime_app_contract(cfg, monkeypatch):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    from agent import agentcore_app

    class Fake:
        key = "k"

        def json_call(self, system, user, **kw):
            return models.Result({"ok": True}, "m0", kw["rung"], 3, 2, 0.0, 12.0)

    monkeypatch.setattr(agentcore_app, "_client", Fake())
    tc = TestClient(agentcore_app.app)
    assert tc.get("/ping").json() == {"status": "Healthy"}
    r = tc.post("/invocations", json={"system": "s", "user": "u", "rung": 0, "purpose": "classify"})
    assert r.status_code == 200 and r.json()["data"] == {"ok": True}
    assert tc.post("/invocations", json={"system": "s", "user": "u", "purpose": "rm -rf"}).status_code == 422


def test_runtime_stack_is_public_mode_with_a_narrow_role():
    from pathlib import Path

    import yaml

    from tests.test_cfn_phase3 import CfnLoader

    t = yaml.load((Path(__file__).resolve().parent.parent / "infra/cfn/agentcore.yaml").read_text(encoding="utf-8"),
                  Loader=CfnLoader)
    rt = t["Resources"]["Runtime"]["Properties"]
    assert rt["NetworkConfiguration"]["NetworkMode"] == "PUBLIC"  # never in the VPC: it has no database access
    assert "OnlyDeployableEnvironments" in t["Rules"]
    stmts = t["Resources"]["RuntimeRole"]["Properties"]["Policies"][0]["PolicyDocument"]["Statement"]
    ssm = next(s for s in stmts if s["Sid"] == "ModelKeyOnly")
    assert ssm["Action"] == "ssm:GetParameter" and "OPENROUTER_API_KEY" in str(ssm["Resource"])
    actions = [a for s in stmts for a in (s["Action"] if isinstance(s["Action"], list) else [s["Action"]])]
    assert not [a for a in actions if a.split(":")[0] in ("rds", "rds-db", "dynamodb", "sqs", "secretsmanager")]
