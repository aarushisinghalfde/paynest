"""Text fingerprints for dedupe and incidents: masked text, normalised, as character 4-grams."""
import re

_TOKEN = re.compile(r"<[A-Z_]+_\d+>")
_NOISE = re.compile(r"\b(?:re|fw|fwd)\s*:|following up on my earlier ticket pn-\d+[.,]?|no reply yet[.,]?|"
                    r"second request\s*-?|please (?:help|check|fix)[.!]?", re.I)
EXPLICIT_REF = re.compile(r"(?:earlier|previous|my) ticket (PN-\d+)", re.I)


def normalise(text: str) -> str:
    t = _NOISE.sub(" ", _TOKEN.sub(" ", text or ""))
    t = re.sub(r"\d+", "0", t.lower())
    return re.sub(r"[^\wऀ-ॿ؀-ۿ]+", " ", t).strip()


def shingles(text: str, n: int = 4) -> set[str]:
    t = normalise(text)
    return {t[i:i + n] for i in range(max(0, len(t) - n + 1))}


def jaccard(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


# What a ticket is about, the same in any wording or language: the thing and the symptom. Character
# shingles miss a burst written three ways ("Payslip PDF is blank / net pay 0", "Cannot download my
# payslip... zero values", "Payslip blank aa rahi hai"), which split the Meridian outage into 2 incidents.
CONCEPTS = {
    "payslip": r"pay ?slips?|payslip|पेस्लिप|पे ?स्लिप|قسيمة|قسائم|كشف الراتب|كشوف الرواتب",
    "document": r"pdf|file|report|फ़ाइल|फाइल|ملف",
    "blank": r"blank|empty|zero|khali|net pay 0|values? 0|खाली|शून्य|فارغ|صفر",
    "download": r"download|डाउनलोड|تنزيل|تحميل",
    "login": r"log ?in|sign ?in|sso|password|otp|लॉगिन|تسجيل الدخول",
    "salary_credit": r"not credited|credit(?:ed)? nahi|jama nahi|जमा नहीं|لم يتم إيداع|salary (?:not|missing)",
    "run_stuck": r"stuck|processing|atka|अटका|عالق",
    "bank_file": r"bank file|neft|wps|sif|بنك",
    "error_5xx": r"\b50[0-4]\b|server error|internal error|timeout|timed out",
    "api_auth": r"\b401\b|\b403\b|token|unauthori[sz]ed",
    "pf": r"\be?pf\b|provident|ecr|uan",
    "tds": r"\btds\b|income tax|form 16",
    "attendance": r"attendance|punch|biometric|हाजिरी|الحضور",
    "leave": r"\bleave|chhutti|छुट्टी|إجازة",
}
GENERIC = {"document", "download"}
SUBJECTS = set(CONCEPTS) - GENERIC - {"blank"}
_CONCEPT_RE = {k: re.compile(v, re.I) for k, v in CONCEPTS.items()}


def concepts(text: str) -> set[str]:
    t = _TOKEN.sub(" ", text or "")
    return {k for k, rx in _CONCEPT_RE.items() if rx.search(t)}


def same_issue(a_text: str, a_sh: set, b_text: str, b_sh: set) -> float:
    """Incident similarity: the wording, or failing that the same subject and symptom in other words or
    another language ("payslip" + "blank"). A shared subject alone never makes a burst."""
    score = jaccard(a_sh, b_sh)
    ca, cb = concepts(a_text), concepts(b_text)
    shared = ca & cb
    # a subject both share (payslip, login, PF...) plus a symptom; "document"/"download" alone are too generic
    if shared & SUBJECTS and len(shared - GENERIC) >= 2:
        score = max(score, len(shared) / len(ca | cb))
    return score


# "following up" counts only about our own earlier message, not about something else: the Q3 template
# "Following up on the refund promised last month" is sent by many customers and is not a resubmit
# (it made 2 of 28 predicted duplicates wrong, 93% precision).
RESUBMIT_MARKER = re.compile(r"(?:^|\s)(?:re|fw|fwd)\s*:|following up on (?:my|our|the) (?:earlier |previous |last |original )?"
                             r"(?:ticket|request|query|email|mail|message|case)|second request|earlier ticket|previous ticket|"
                             r"no reply|still waiting|again\b|dobara|phir se|مرة أخرى|फिर से", re.I)
_STOP = {"the", "a", "an", "of", "for", "to", "in", "on", "and", "or", "is", "are", "was", "with", "by", "our", "we",
         "my", "this", "that", "it", "be", "from", "at", "not", "but", "has", "have", "after", "before"}


def words(text: str) -> set[str]:
    return {w for w in normalise(text).split() if len(w) > 2 and w not in _STOP}


def containment(small: set, big: set) -> float:
    """Share of `small` found in `big` (an issue summary inside a longer ticket)."""
    return len(small & big) / len(small) if small else 0.0
