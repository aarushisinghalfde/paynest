"""Who the customer is, how urgent the ticket is, and what a late answer costs (MSA Schedule 3).

Every ticket gets a priority (P1-P3, contract definitions), a respond-by and a resolve-by time from the
customer's tier, and the service credit the client would owe if the resolution target is missed
(monthly fee x credit %, x1.5 past twice the target). The console orders work by these deadlines.
"""
import re
from datetime import UTC, datetime, timedelta
from functools import lru_cache

import yaml

from shared import settings

ORDER = {"P1": 1, "P2": 2, "P3": 3}


@lru_cache(maxsize=1)
def terms() -> dict:
    with open(settings.ROOT / "config" / "sla.yaml", encoding="utf-8") as fh:
        t = yaml.safe_load(fh)
    t["_rx"] = {p: re.compile(rx, re.IGNORECASE) for p, rx in t["priority"].items()}
    return t


def priority(text: str, risk: dict | None = None, classification: dict | None = None,
             customer_pick: str | None = None) -> tuple[str, str]:
    """(P1|P2|P3, why). Contract 3.2: P1 payroll cannot run, pay late or a filing missed; P2 a material
    error in payroll output or a degraded module; P3 everything else."""
    t, c, r = terms(), classification or {}, risk or {}
    if "payment_blocked" in (r.get("money") or []) or c.get("priority_signal") or t["_rx"]["P1"].search(text or ""):
        ours, why = "P1", "pay or a filing at risk"
    elif t["_rx"]["P2"].search(text or ""):
        ours, why = "P2", "error in payroll output or a degraded module"
    else:
        ours, why = "P3", "how-to, configuration or other"
    pick = (customer_pick or "").upper()
    if pick in ORDER and ORDER[pick] < ORDER[ours]:  # never lowered without notice to the customer
        return pick, f"customer set {pick} (we read {ours}: {why})"
    return ours, why


def assess(tenant: dict | None, prio: str, created_at=None) -> dict:
    """Deadlines and money at stake for one ticket. Unknown tenant: no contract to apply (triage desk)."""
    t = terms()
    created = _dt(created_at) or datetime.now(UTC)
    tenant = tenant or {}
    tier = tenant.get("tier") or "Standard"
    term = (t["tiers"].get(tier) or {}).get(prio)
    out = {"priority": prio, "tier": tier, "customer": tenant.get("name") or tenant.get("tenant_id"),
           "template": t["template"], "created_at": created.isoformat()}
    if not term:
        return {**out, "best_effort": True}
    fee = float(tenant.get("monthly_fee_usd") or 0)
    credit = round(fee * term["credit_pct"] / 100, 2)
    return {**out, "best_effort": False,
            "respond_by": (created + timedelta(hours=term["first_response_h"])).isoformat(),
            "resolve_by": (created + timedelta(hours=term["resolution_h"])).isoformat(),
            "resolution_h": term["resolution_h"],
            "credit_usd": credit, "credit_usd_after_2x": round(credit * t["severity_multiplier"], 2)}


def state_of(s: dict | None, done: bool, now=None) -> str | None:
    """on_track | at_risk | breached for an open ticket; met | missed once done (resolution clock only)."""
    if not s or s.get("best_effort") or not s.get("resolve_by"):
        return None
    now = _dt(now) or datetime.now(UTC)
    start, due = _dt(s["created_at"]), _dt(s["resolve_by"])
    if done:
        return None  # the console marks done tickets from their reply time
    if now >= due:
        return "breached"
    return "at_risk" if (now - start) >= (due - start) * terms()["at_risk_share"] else "on_track"


def _dt(v):
    if v is None:
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=UTC)
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=UTC)
    except ValueError:
        return None
