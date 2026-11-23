"""Normalise labels typed by customers, agents and partners.

Category: the 35 spellings in the export map onto the 9 SOP categories (ticket_triage_sop.md),
each owned by one queue. Priority: P1-P3 from P-codes, widget words and partner S-codes.
Language: en, hi (Devanagari), ar (Arabic script) or hi-Latn (Hinglish).
"""

import re

TEAMS = {  # SOP category -> owning queue
    "Payroll": "Payroll-Ops",
    "Statutory": "Statutory-Compliance",
    "How-To": "General-L1",
    "Reports": "Reports-Analytics",
    "Leave & Attendance": "Leave-Attendance",
    "Integration": "Integrations",
    "Billing": "Billing",
    "Access / Login": "Access-Support",
    "Onboarding": "Onboarding",
}
QUEUE_TEAM = {q: t for t, q in TEAMS.items()}

# Keys are spellings with everything but letters removed, lower-cased.
_CATEGORY_KEYS = {
    "payroll": "Payroll",
    "payrollrun": "Payroll",
    "payrollissue": "Payroll",
    "statutory": "Statutory",
    "statutorycompliance": "Statutory",
    "compliancepfwps": "Statutory",
    "howto": "How-To",
    "reports": "Reports",
    "reportexport": "Reports",
    "leaveattendance": "Leave & Attendance",
    "leave": "Leave & Attendance",
    "integration": "Integration",
    "integrations": "Integration",
    "apiintegration": "Integration",
    "integrationbug": "Integration",
    "billing": "Billing",
    "billinginvoices": "Billing",
    "accesslogin": "Access / Login",
    "loginissue": "Access / Login",
    "access": "Access / Login",
    "onboarding": "Onboarding",
    "newcustomersetup": "Onboarding",
}


def category_team(raw: str | None) -> str | None:
    """'PAYROLL ISSUE', 'payroll-run', 'Payroll Run' -> 'Payroll'. Unknown -> None."""
    if not raw:
        return None
    return _CATEGORY_KEYS.get(re.sub(r"[^a-z]", "", raw.lower()))


def queue_team(queue: str | None) -> str | None:
    return QUEUE_TEAM.get(queue or "")


_PRIORITY = {
    "p1": "P1",
    "p2": "P2",
    "p3": "P3",
    "urgent": "P1",
    "high": "P2",
    "normal": "P3",
    "low": "P3",
    "s1": "P1",
    "s2": "P2",
    "s3": "P3",
}


def priority(raw: str | None) -> str | None:
    return _PRIORITY.get((raw or "").strip().lower())


def case_status(raw: str | None) -> str | None:
    """closed / CLOSED / Closed -> closed; solved / Resolved -> resolved."""
    s = (raw or "").strip().lower()
    return {"solved": "resolved"}.get(s, s) or None


_HINGLISH = {
    # live misses: "kaise download karun slip?", "kahan se khulegi ye guide?"
    "karun", "karu", "karein", "karen", "kahan", "kahaan", "khulegi", "khulega", "khule", "milega", "milegi",
    "mujhe", "hume", "humein", "aap", "aapka", "batao", "bataiye", "chahta", "chahti", "dekhna", "nikalna",
    "kaun", "kidhar", "yeh", "ye", "woh", "se", "ko", "ki", "ke", "ka", "hoti", "hota", "sakta", "sakti",
    "hai",
    "nahi",
    "kya",
    "karo",
    "kar",
    "raha",
    "rahi",
    "rahe",
    "kaise",
    "kyun",
    "hoga",
    "gaya",
    "diya",
    "abhi",
    "bhi",
    "wale",
    "liye",
    "logon",
    "dikh",
    "aaya",
    "aayi",
    "mera",
    "meri",
    "hamare",
    "humare",
    "kab",
    "kitna",
    "tha",
    "thi",
    "nahin",
    "hain",
    "aur",
    "karna",
    "chahiye",
}


def language(text: str) -> str:
    if re.search(r"[ऀ-ॿ]", text):
        return "hi"
    if re.search(r"[؀-ۿ]", text):
        return "ar"
    words = set(re.findall(r"[a-z]+", text.lower()))
    hits = words & _HINGLISH
    # two Hinglish words, at least one not a short particle ("ki", "ka" are also names and initials)
    return "hi-Latn" if len(hits) >= 2 and any(len(w) >= 4 for w in hits) else "en"
