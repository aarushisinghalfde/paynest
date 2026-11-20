"""Keyword rules for the phase 5 classifier (phase 6 adds similar-ticket match and models).

Lower-cased substrings per SOP team, in English, Hinglish, Hindi and Arabic. Score = number
of keyword hits; confidence = the winning team's share of all hits.
"""

KEYWORDS = {
    "Statutory": [
        "pf ",
        "epf",
        "esi",
        "tds",
        "professional tax",
        " pt ",
        "wps",
        "sif",
        "gratuity",
        "ecr",
        "statutory",
        "compliance",
        "भविष्य निधि",
        "टीडीएस",
        "حماية الأجور",
        "مكافأة نهاية الخدمة",
    ],
    "Payroll": [
        "payroll",
        "salary",
        "net pay",
        "payslip",
        "arrears",
        "bank file",
        "processing",
        "salary nahi",
        "वेतन",
        "पेरोल",
        "الرواتب",
        "راتب",
        "مسير",
    ],
    "How-To": ["how to", "how do i", "how can", "where can i", "kaise", "steps to", "कैसे", "كيف"],
    "Reports": ["report", "export", "register", "download all", "रिपोर्ट", "تقرير"],
    "Leave & Attendance": [
        "leave",
        "attendance",
        "punch",
        "overtime",
        "shift",
        "छुट्टी",
        "उपस्थिति",
        "إجازة",
        "حضور",
    ],
    "Integration": ["api", "integration", "sync", "webhook", "connector", "hris", "import", "تكامل"],
    "Billing": ["invoice", "billing", "subscription", "credit note", "charged", "बिल", "فاتورة"],
    "Access / Login": [
        "login",
        "password",
        "sso",
        "locked",
        "otp",
        "access",
        "लॉगिन",
        "كلمة المرور",
        "تسجيل الدخول",
    ],
    "Onboarding": [
        "new employee",
        "onboard",
        "bulk upload",
        "new customer",
        "setup",
        "नया कर्मचारी",
        "موظف جديد",
    ],
}


def classify(text: str) -> dict:
    t = f" {text.lower()} "
    scores = {team: sum(t.count(k) for k in words) for team, words in KEYWORDS.items()}
    total = sum(scores.values())
    if not total:
        return {"team": None, "confidence": 0.0, "scores": {}, "source": "keywords"}
    team = max(scores, key=lambda k: (scores[k], -list(KEYWORDS).index(k)))
    return {
        "team": team,
        "confidence": round(scores[team] / total, 3),
        "scores": {k: v for k, v in scores.items() if v},
        "source": "keywords",
    }
