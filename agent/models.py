"""One model client for every job (classify, draft, judge), reading config/models.yaml.

Provider is OpenRouter while Bedrock is on hold; switching is the `provider` line. Every
call: only masked text, a JSON response, tokens and cost written to the cost ledger, and the
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
        self, ledger=None, transport=_post, cap_usd: float | None = None, api_key: str | None = None
    ):
        cfg = config()
        self.provider = cfg["provider"]
        p = cfg["providers"][self.provider]
        self.ladder = p["ladder"]
        self.base_url = p.get("base_url")
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
