"""The YAML router: first matching rule wins; every decision carries the rule id and reason."""
from functools import lru_cache

import yaml

from shared import settings


@lru_cache(maxsize=1)
def rules() -> list[dict]:
    with open(settings.ROOT / "config" / "router.yaml", encoding="utf-8") as fh:
        return yaml.safe_load(fh)["rules"]


def facts_from_state(state: dict) -> dict:
    c = state.get("classification") or {}
    return {
        "injection": bool(state.get("injection_rules")) or bool(c.get("is_injection")),
        "injection_rules": ",".join(state.get("injection_rules") or []) or "classifier",
        "pii_blocked": state.get("route") == "block",
        "tenant_known": state.get("tenant") is not None,
        "incident": bool(state.get("incident_id")), "incident_size": state.get("incident_size", ""),
        "duplicate": bool(state.get("duplicate_of")), "duplicate_of": state.get("duplicate_of"),
        "duplicate_reason": state.get("duplicate_reason", ""),
        "jira": bool(state.get("jira_key")), "jira_key": state.get("jira_key"),
        "team": state.get("team"), "second": c.get("second"), "branch": c.get("branch", "auto"),
        "priority_signal": bool(c.get("priority_signal")),
        "smalltalk": state.get("talk") in ("greeting", "thanks", "status"),
        "vague": state.get("talk") == "vague",
    }


def decide(facts: dict) -> dict:
    for rule in rules():
        if all(facts.get(k) == v for k, v in rule["when"].items()):
            return {"route": rule["route"], "rule": rule["id"], "queue": rule.get("queue"),
                    "reason": rule["reason"].format_map({k: (v if v is not None else "?") for k, v in facts.items()})}
    raise RuntimeError("router has no default rule")
