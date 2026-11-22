"""Phase E: the agent's model steps hosted on Bedrock AgentCore Runtime (Sydney).

Our split, chosen for this system: the ticket graph, the database, the PII vault and the queue stay
on the app server in the VPC; AgentCore hosts the MODEL STEPS only (classify, draft, translate,
judge). What crosses to AgentCore is what already crosses to a model today: masked text and the
masked sources. So the runtime needs no database credentials, no VPC attachment (PUBLIC network
mode, no NAT bill) and no access to raw data, and it can be scaled, versioned and swapped
(OpenRouter now, Bedrock models once the account hold is lifted) without touching the agent.

Contract (AgentCore HTTP protocol, port 8080):
  GET  /ping         -> {"status": "Healthy"}
  POST /invocations  {"system": str, "user": str, "rung": int, "purpose": str, "max_tokens": int}
                     -> {"data": {...}, "model": str, "rung": int, "tokens_in": int, "tokens_out": int,
                         "cost_usd": float, "ms": float}      or HTTP 502 {"error": "..."}
The app server reaches it with provider: agentcore (agent/models.py), signed by its instance role.
Started by the image's default command (Dockerfile); the compose services override it.
"""

import os

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from agent.models import BudgetExceeded, ModelClient, ModelError

app = FastAPI(title="Payce agent model steps (AgentCore)")
_client = None
PURPOSES = {"classify", "draft", "draft_howto", "translate", "judge"}


def _secrets_from_ssm():
    """The provider key lives in SSM (SecureString), read once with the runtime role; never in env config."""
    name = os.environ.get("MODEL_KEY_PARAM")
    if not name or os.environ.get("OPENROUTER_API_KEY"):
        return
    import boto3

    value = boto3.client("ssm").get_parameter(Name=name, WithDecryption=True)["Parameter"]["Value"]
    os.environ["OPENROUTER_API_KEY"] = value


def client() -> ModelClient:
    global _client
    if _client is None:
        _secrets_from_ssm()
        # the backend behind the runtime: openrouter today, bedrock later (AGENTCORE_BACKEND)
        backend = os.environ.get("AGENTCORE_BACKEND") or "openrouter"
        if backend == "agentcore":  # the runtime calling itself would loop
            raise RuntimeError("AGENTCORE_BACKEND must be openrouter or bedrock")
        _client = ModelClient(provider=backend)
    return _client


class Call(BaseModel):
    system: str = Field(max_length=20_000)
    user: str = Field(max_length=40_000)
    rung: int = Field(default=0, ge=0, le=3)
    purpose: str = "classify"
    max_tokens: int = Field(default=400, ge=16, le=2000)


@app.get("/ping")
def ping() -> dict:
    return {"status": "Healthy"}


@app.post("/invocations")
def invoke(call: Call) -> dict:
    if call.purpose not in PURPOSES:
        raise HTTPException(422, f"purpose must be one of {sorted(PURPOSES)}")
    c = client()
    if not c.key:
        raise HTTPException(502, "no model backend configured in the runtime")
    try:
        r = c.json_call(call.system, call.user, rung=call.rung, purpose=call.purpose, max_tokens=call.max_tokens)
    except BudgetExceeded as exc:
        raise HTTPException(429, str(exc)) from None
    except ModelError as exc:
        raise HTTPException(502, str(exc)) from None
    return {"data": r.data, "model": r.model, "rung": r.rung, "tokens_in": r.tokens_in, "tokens_out": r.tokens_out,
            "cost_usd": r.cost_usd, "ms": round(r.ms, 1)}
