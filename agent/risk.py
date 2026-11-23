"""Risk policy: what the customer asks for decides whether the agent may act on its own.

The agent answers information questions (how to, run status) itself. It never moves money, changes bank
details or releases personal data: those are handed to a person, and the amount and the kind of data
decide which person (config/risk.yaml). Runs on masked text; returns labels and amounts only.
"""
import re
from functools import lru_cache

import yaml

from shared import settings

AMOUNT_RE = re.compile(
    r"(?P<cur>INR|Rs\.?|₹|AED|USD|\$|dirhams?|rupees?)?\s?(?P<num>\d[\d,]*(?:\.\d+)?)\s?"
    r"(?P<unit>lakh|lac|crore|cr|k)?\b\s?(?P<cur2>INR|AED|USD|rupees?|dirhams?)?", re.IGNORECASE)
CURRENCY = {"inr": "INR", "rs": "INR", "rs.": "INR", "₹": "INR", "rupee": "INR", "rupees": "INR",
            "aed": "AED", "dirham": "AED", "dirhams": "AED", "usd": "USD", "$": "USD"}
UNIT = {"lakh": 100_000, "lac": 100_000, "crore": 10_000_000, "cr": 10_000_000, "k": 1_000}


@lru_cache(maxsize=1)
def policy() -> dict:
    with open(settings.ROOT / "config" / "risk.yaml", encoding="utf-8") as fh:
        p = yaml.safe_load(fh)
    p["_money"] = {k: re.compile(v, re.IGNORECASE) for k, v in p["money_actions"].items()}
    p["_private"] = {k: re.compile(v, re.IGNORECASE) for k, v in p["private_data"].items()}
    p["_legal"] = re.compile(p["legal"], re.IGNORECASE)
    return p


def amounts(text: str, region: str | None) -> list[tuple[str, float, str]]:
    """Money amounts written with a currency or a unit (lakh, crore). The tenant's currency is assumed
    for "50 lakh" and for a bare number right after a money word ("refund 85000")."""
    home = {"IN": "INR", "UAE": "AED"}.get(region or "", "USD")
    out = []
    for m in AMOUNT_RE.finditer(text or ""):
        cur = (m.group("cur") or m.group("cur2") or "").lower().rstrip(".") or ""
        unit = (m.group("unit") or "").lower()
        before = text[max(0, m.start() - 25):m.start()].lower()
        money_word = re.search(r"(refund|amount|pay|salary|payment|of|for)\s*$", before)
        if not cur and not unit and not money_word:
            continue
        num = float(m.group("num").replace(",", ""))
        if not cur and not unit and num < 100:  # "refund 2 employees" is not an amount
            continue
        out.append((CURRENCY.get(cur, CURRENCY.get(cur + ".", home)) if cur else home, num * UNIT.get(unit, 1),
                    m.group(0).strip()))  # as the customer wrote it: the reply repeats their words, not ours
    return out


def assess(text: str, region: str | None) -> dict:
    """{"money": [kinds], "private": [kinds], "legal": bool, "amount": "INR 150,000" | None,
    "second_approver": bool} for the router; empty lists when it is an information question."""
    p = policy()
    money = [k for k, rx in p["_money"].items() if rx.search(text or "")]
    private = [k for k, rx in p["_private"].items() if rx.search(text or "")]
    amt = max(amounts(text, region), key=lambda a: a[1] / p["second_approver_at"].get(a[0], 1), default=None) \
        if money else None
    limit = p["second_approver_at"].get(amt[0]) if amt else None
    return {
        "money": money, "private": private, "legal": bool(p["_legal"].search(text or "")),
        "amount": f"{amt[0]} {amt[1]:,.0f}" if amt else None,
        "amount_said": amt[2] if amt else None,
        "second_approver": bool(amt and limit and amt[1] >= limit),
        "limit": f"{amt[0]} {limit:,.0f}" if amt and limit else None,
    }
