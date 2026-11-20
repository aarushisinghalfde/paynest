"""Phase 8 tools. Read-only, deterministic, and each result carries its own source id.

The drafter never calls tools itself: plan() picks them from the masked text with plain
rules, and their results go into the prompt as FACTS the reply may cite.
  get_rate            statutory value in force on the question date (rule table)
  get_run_status      payroll run status from the payroll API (mock in the demo)
  get_tenant_profile  tier and region only (no fees, no contacts)
  get_incident        the open incident this ticket is attached to, if any
"""

import json
import re
import urllib.error
import urllib.request
from datetime import date

from loader import knowledge

RATE_TRIGGERS = [  # (pattern, region, topic): English/Hinglish, Hindi and Arabic terms
    (re.compile(r"\b(e?pf|provident fund|wage ceiling|pf ceiling)\b|भविष्य निधि|पीएफ", re.I), "IN", "pf_wage_ceiling"),
    (re.compile(r"\b(wps|sif|edr)\b|حماية الأجور|نظام حماية|ملف الرواتب", re.I), "UAE", "wps_file_format"),
    (re.compile(r"\b(tds|tax slabs?|income tax slab)\b|टीडीएस|आयकर", re.I), "IN", "tds"),
    (re.compile(r"\b(gratuity|end[- ]of[- ]service)\b|مكافأة نهاية الخدمة|نهاية الخدمة", re.I), "UAE", "gratuity"),
]
RUN_ID_RE = re.compile(r"\b(?:run[ _-]?(?:id)?[ :#-]*)?((?:PR|RUN)-?\d{3,}[A-Z0-9-]*)\b", re.I)


def get_rate(rules: list[dict], region: str, topic: str, as_of: date) -> dict | None:
    r = knowledge.get_rate(rules, region, topic, as_of)
    if r is None:
        return None
    rule = next(x for x in rules if x["rule_id"] == r["rule_id"])
    return {"tool": "get_rate", "source": f"{r['rule_id']}#rule", "topic": topic, "as_of": as_of.isoformat(),
            "title": rule["title"], **{k: (v.isoformat() if isinstance(v, date) else v) for k, v in r.items()}}


def get_run_status(run_id: str, base_url: str, timeout: float = 5.0, opener=urllib.request.urlopen) -> dict:
    url = f"{base_url.rstrip('/')}/payroll-runs/{urllib.request.quote(run_id)}/status"
    try:
        with opener(url, timeout=timeout) as r:  # noqa: S310 - internal payroll API
            data = json.loads(r.read())
    except urllib.error.HTTPError as e:
        return {"tool": "get_run_status", "source": f"payroll-api:{run_id}", "run_id": run_id,
                "error": "rate_limited" if e.code == 429 else f"http_{e.code}"}
    except (urllib.error.URLError, TimeoutError, ValueError):
        return {"tool": "get_run_status", "source": f"payroll-api:{run_id}", "run_id": run_id, "error": "unavailable"}
    return {"tool": "get_run_status", "source": f"payroll-api:{run_id}", "run_id": run_id,
            "status": data.get("status"), "stage": data.get("stage")}


def get_tenant_profile(tenant: dict | None) -> dict | None:
    if not tenant:
        return None
    return {"tool": "get_tenant_profile", "source": f"tenant:{tenant['tenant_id']}", "tier": tenant.get("tier"),
            "region": tenant.get("region")}


def get_incident(state: dict) -> dict | None:
    if not state.get("incident_id"):
        return None
    return {"tool": "get_incident", "source": f"incident:{state['incident_id']}", "incident_id": state["incident_id"],
            "linked_tickets": state.get("incident_size")}


def plan(text: str, region: str | None) -> dict:
    """Which tools this ticket needs. A rate topic counts only in the tenant's own region."""
    rates = [(rg, topic) for rx, rg, topic in RATE_TRIGGERS if rx.search(text or "") and (region in (None, rg))]
    runs = [m[1].upper() for m in RUN_ID_RE.finditer(text or "")]
    return {"rates": rates, "runs": runs[:2]}


def run_tools(state: dict, rules: list[dict], as_of: date, payroll_url: str | None, opener=urllib.request.urlopen) -> list[dict]:
    text = f"{state.get('subject', '')} {state.get('body', '')}"
    tenant = state.get("tenant") or {}
    p = plan(text, tenant.get("region"))
    facts = []
    for region, topic in p["rates"]:
        r = get_rate(rules, region, topic, as_of)
        if r:
            facts.append(r)
    if payroll_url:
        facts += [get_run_status(run_id, payroll_url, opener=opener) for run_id in p["runs"]]
    for extra in (get_tenant_profile(tenant or None), get_incident(state)):
        if extra:
            facts.append(extra)
    return facts
