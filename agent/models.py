"""One model client for every job (classify, draft, judge), reading config/models.yaml.

Two providers behind one json_call:
  openrouter  HTTPS + API key (the stand-in while this account's Bedrock is on hold)
  bedrock     the Converse API in ap-southeast-2 with the server's IAM role (no key). Optionally the
              calls run in another account through a cross-account role (BEDROCK_ROLE_ARN), so the
              app can stay here while that account's Bedrock does the model work, in Sydney.
Switching is `provider: bedrock` in config/models.yaml plus the IAM permission (infra/cfn/iam.yaml).
Every call: only masked text, a JSON response, tokens and cost written to the cost ledger, and the
daily cap enforced BEFORE the call (above it, callers fall back to route-to-queue).
"""

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from functools import lru_cache

import yaml

from shared import settings


class BudgetExceeded(RuntimeError):
    pass


class ModelError(RuntimeError):
    pass


@lru_cache(maxsize=1)
def config() -> dict:
    with open(settings.ROOT / "config" / "models.yaml", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


@dataclass
class Result:
    data: dict
    model: str
    rung: int
    tokens_in: int
    tokens_out: int
    cost_usd: float
    ms: float


class MemoryLedger:
    def __init__(self):
        self.rows = []

    def record(self, **row):
        self.rows.append(row)

    def spent_today(self) -> float:
        return sum(r["cost_usd"] for r in self.rows)


class PgLedger:
    def __init__(self, dsn):
        self.dsn = dsn

    def _conn(self):
        import psycopg

        return psycopg.connect(self.dsn, connect_timeout=5)

    def record(self, **row):
        cols = ["ticket_id", "purpose", "route", "model_id", "rung", "tokens_in", "tokens_out", "cost_usd"]
        with self._conn() as conn:
            conn.execute(
                f"INSERT INTO cost_ledger ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))})",
                [row.get(c) for c in cols],
            )

    def spent_today(self) -> float:
        with self._conn() as conn:
            return float(
                conn.execute(
                    "SELECT coalesce(sum(cost_usd), 0) FROM cost_ledger WHERE ts >= date_trunc('day', now())"
                ).fetchone()[0]
            )


def _post(url, payload, key, timeout=30):
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
            "X-Title": "Payce Support Assist",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        return json.loads(resp.read())


class ModelClient:
    def __init__(
        self, ledger=None, transport=_post, cap_usd: float | None = None, api_key: str | None = None,
        provider: str | None = None,
    ):
        cfg = config()
        # MODEL_PROVIDER (SSM /paynest/demo, read at start) switches provider without a release
        self.provider = provider or os.environ.get("MODEL_PROVIDER") or cfg["provider"]
        p = cfg["providers"][self.provider]
        self.ladder = p["ladder"]
        self.base_url = p.get("base_url")
        self.prices = p.get("prices") or {}
        self.region = p.get("region")
        self.role_arn = os.environ.get("BEDROCK_ROLE_ARN", "") if self.provider == "bedrock" else ""
        if self.provider == "agentcore":
            # the model steps run on AgentCore (agent/agentcore_app.py); rungs pass through to its backend
            self.runtime_arn = os.environ.get(p.get("runtime_arn_env", "AGENTCORE_RUNTIME_ARN"), "")
            self.key = "iam" if self.runtime_arn else ""
            self.ladder = self.ladder or ["agentcore"]
            if transport is _post:
                transport = _agentcore_transport(self.region, self.runtime_arn)
        elif self.provider == "bedrock":
            # no key: the instance (or cross-account) role signs each call; "iam" marks the client usable
            self.key = "iam" if self.ladder else ""
            if transport is _post:
                transport = _converse_transport(self.region, self.role_arn)
        else:
            self.key = api_key if api_key is not None else os.environ.get(p.get("api_key_env", ""), "")
        self.cap = cfg["budget"]["daily_usd_cap"] if cap_usd is None else cap_usd
        self.ledger = ledger or MemoryLedger()
        self.transport = transport

    def json_call(
        self,
        system: str,
        user: str,
        rung: int = 0,
        purpose: str = "classify",
        ticket_id=None,
        route=None,
        max_tokens: int = 400,
    ) -> Result:
        if self.ledger.spent_today() >= self.cap:
            raise BudgetExceeded(f"daily model budget USD {self.cap} reached")
        if not self.key:
            raise ModelError("no API key for the model provider")
        model = self.ladder[min(rung, len(self.ladder) - 1)]
        if self.provider == "agentcore":
            return self._agentcore(rung, system, user, purpose, ticket_id, route, max_tokens)
        if self.provider == "bedrock":
            return self._bedrock(model, rung, system, user, purpose, ticket_id, route, max_tokens)
        payload = {
            "model": model,
            "temperature": 0,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
            "usage": {"include": True},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }
        t0 = time.perf_counter()
        try:
            out = self.transport(f"{self.base_url}/chat/completions", payload, self.key)
        except (urllib.error.URLError, TimeoutError) as exc:
            raise ModelError(f"provider call failed: {type(exc).__name__}") from None
        ms = (time.perf_counter() - t0) * 1000
        usage = out.get("usage") or {}
        cost = float(usage.get("cost") or 0.0)
        self.ledger.record(
            ticket_id=ticket_id,
            purpose=purpose,
            route=route,
            model_id=model,
            rung=rung,
            tokens_in=usage.get("prompt_tokens"),
            tokens_out=usage.get("completion_tokens"),
            cost_usd=cost,
        )
        try:
            text = out["choices"][0]["message"]["content"]
            data = json.loads(text[text.find("{") : text.rfind("}") + 1])
        except (KeyError, IndexError, ValueError) as exc:
            raise ModelError("response was not JSON") from exc
        return Result(
            data, model, rung, usage.get("prompt_tokens") or 0, usage.get("completion_tokens") or 0, cost, ms
        )

    def _agentcore(self, rung, system, user, purpose, ticket_id, route, max_tokens) -> Result:
        t0 = time.perf_counter()
        try:
            out = self.transport({"system": system, "user": user, "rung": rung, "purpose": purpose,
                                  "max_tokens": max_tokens})
        except ModelError:
            raise
        except Exception as exc:  # noqa: BLE001 - throttling, access, network: the caller falls back
            code = getattr(exc, "response", {}).get("Error", {}).get("Code", type(exc).__name__)
            raise ModelError(f"agentcore call failed: {code}") from None
        ms = (time.perf_counter() - t0) * 1000
        cost = float(out.get("cost_usd") or 0.0)
        model = f"agentcore:{out.get('model')}"
        self.ledger.record(ticket_id=ticket_id, purpose=purpose, route=route, model_id=model, rung=rung,
                           tokens_in=out.get("tokens_in"), tokens_out=out.get("tokens_out"), cost_usd=cost)
        if not isinstance(out.get("data"), dict):
            raise ModelError("agentcore response had no JSON data")
        return Result(out["data"], model, rung, out.get("tokens_in") or 0, out.get("tokens_out") or 0, cost, ms)

    def _bedrock(self, model, rung, system, user, purpose, ticket_id, route, max_tokens) -> Result:
        t0 = time.perf_counter()
        try:
            out = self.transport(model=model, system=system, user=user, max_tokens=max_tokens)
        except Exception as exc:  # noqa: BLE001 - throttling, access, network: the caller falls back
            code = getattr(exc, "response", {}).get("Error", {}).get("Code", type(exc).__name__)
            raise ModelError(f"bedrock call failed: {code}") from None
        ms = (time.perf_counter() - t0) * 1000
        usage = out.get("usage") or {}
        tin, tout = int(usage.get("inputTokens") or 0), int(usage.get("outputTokens") or 0)
        price = self.prices.get(model) or {}
        cost = tin / 1000 * float(price.get("in", 0)) + tout / 1000 * float(price.get("out", 0))
        self.ledger.record(ticket_id=ticket_id, purpose=purpose, route=route, model_id=model, rung=rung,
                           tokens_in=tin, tokens_out=tout, cost_usd=cost)
        try:
            text = "".join(c.get("text", "") for c in out["output"]["message"]["content"])
            data = json.loads(text[text.find("{") : text.rfind("}") + 1])
        except (KeyError, ValueError) as exc:
            raise ModelError("response was not JSON") from exc
        return Result(data, model, rung, tin, tout, cost, ms)


def _agentcore_transport(region: str, runtime_arn: str):
    """bedrock-agentcore InvokeAgentRuntime, signed by the instance role. One session id per call:
    the model steps are stateless, so no session state is kept between tickets."""
    import uuid

    state = {"client": None}

    def call(payload: dict) -> dict:
        if state["client"] is None:
            import boto3

            state["client"] = boto3.client("bedrock-agentcore", region_name=region)
        r = state["client"].invoke_agent_runtime(agentRuntimeArn=runtime_arn, qualifier="DEFAULT",
                                                 runtimeSessionId=f"paynest-{uuid.uuid4().hex}",
                                                 contentType="application/json", accept="application/json",
                                                 payload=json.dumps(payload).encode())
        body = r["response"].read() if hasattr(r["response"], "read") else r["response"]
        out = json.loads(body)
        if r.get("statusCode", 200) >= 400 or "error" in out or "detail" in out:
            raise ModelError(f"agentcore: {out.get('error') or out.get('detail')}")
        return out

    return call


def _converse_transport(region: str, role_arn: str = ""):
    """bedrock-runtime Converse, signed by the instance role, or by a cross-account role (refreshed hourly)."""
    state = {"client": None, "expires": 0.0}

    def client():
        import boto3

        if state["client"] is not None and time.time() < state["expires"]:
            return state["client"]
        if role_arn:
            creds = boto3.client("sts", region_name=region).assume_role(
                RoleArn=role_arn, RoleSessionName="paynest-models", DurationSeconds=3600)["Credentials"]
            state["client"] = boto3.client("bedrock-runtime", region_name=region,
                                           aws_access_key_id=creds["AccessKeyId"],
                                           aws_secret_access_key=creds["SecretAccessKey"],
                                           aws_session_token=creds["SessionToken"])
            state["expires"] = time.time() + 3000
        else:
            state["client"], state["expires"] = boto3.client("bedrock-runtime", region_name=region), float("inf")
        return state["client"]

    def call(model, system, user, max_tokens):
        return client().converse(modelId=model, system=[{"text": system}],
                                 messages=[{"role": "user", "content": [{"text": user}]}],
                                 inferenceConfig={"maxTokens": max_tokens, "temperature": 0})

    return call
