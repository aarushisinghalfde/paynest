"""Mask personal data in a ticket body.

Order of work:
  1. normalise native digits (Arabic-Indic, Devanagari) to 0-9 for detection;
  2. run the recognisers below on the normalised text (identifiers are checksum-validated);
  2b. when Presidio is installed, steps 2 and 3 run as one Presidio pipeline (our
     recognisers are registered in its registry) and spaCy adds person names found
     anywhere in a sentence (pii/presidio_layer.py);
  3. find names: the sender's name (every script), names introduced by phrases such as
     "my name is", "employee", "मेरा नाम", "اسمي", and sign-offs; then every other
     occurrence of those names;
  4. resolve overlaps (longest wins) and replace each value with a per-ticket token such as
     <IBAN_1>. The same value always gets the same token within a ticket.

Over-masking is preferred to leaking: an unknown long number is masked as <ACCOUNT_n>.
"""
import re
from dataclasses import dataclass, field

from pii import presidio_layer
from pii.normalize import normalize_digits
from pii.validators import IFSC_RE, PAN_RE, iban_valid, is_aadhaar, is_emirates_id

ND = r"(?<!\d)"  # no digit before
NA = r"(?!\d)"   # no digit after
SEP = r"[ \-]?"

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)+")
IBAN_RE = re.compile(r"(?<![A-Za-z0-9])[A-Z]{2}\d{2}(?: ?[A-Z0-9]){11,30}(?![A-Za-z0-9])")
EMIRATES_ID_RE = re.compile(ND + r"784" + SEP + r"\d{4}" + SEP + r"\d{7}" + SEP + r"\d" + NA)
TWELVE_RE = re.compile(ND + r"\d{4}" + SEP + r"\d{4}" + SEP + r"\d{4}" + NA)
PHONE_IN_RE = re.compile(r"(?:\+91[ \-]?|(?<!\d)0)?" + ND + r"[6-9]\d{4}" + SEP + r"\d{5}" + NA)
PHONE_AE_RE = re.compile(
    r"(?:\+971|00971|(?<!\d)0)" + SEP + r"(?:5\d|[2-9])" + SEP + r"\d{3}" + SEP + r"\d{4}" + NA
)
LONG_NUMBER_RE = re.compile(ND + r"\d{9,18}" + NA)
UAN_CONTEXT_RE = re.compile(r"(?i:\bUAN\b|यूएएन|يو\s?ايه\s?ان)")
AADHAAR_CONTEXT_RE = re.compile(r"(?i:\baadhaa?r\b|आधार)")

LATIN_NAME = r"[A-Z][a-z]+(?:[ \-][A-Z][a-z]+){0,2}"
DEVA_NAME = r"[\u0900-\u097F]+(?: [\u0900-\u097F]+)?"
ARAB_NAME = r"[\u0621-\u064A]+(?: [\u0621-\u064A]+)?"

NAME_PATTERNS = [
    # English and Hinglish
    re.compile(r"(?i:\bmy name is|\bi am|\bi'm|\bthis is)\s+(" + LATIN_NAME + r")"),
    re.compile(r"(?i:\bemployee|\bcolleague|\bstaff member|\bmr\.?|\bmrs\.?|\bms\.?|\bdr\.?)\s+("
               + LATIN_NAME + r")"),
    re.compile(r"(?i:\bmera naam|\bmeraa naam|\bnaam)\s+(" + LATIN_NAME + r")"),
    re.compile(r"(?i:\b(?:regards|thanks|thank you|sincerely|cheers|dhanyavaad|shukriya))"
               r"[,.!]?[ \t]*\n+[ \t]*(" + LATIN_NAME + r")"),
    # Hindi
    re.compile(r"(?:मेरा नाम|नाम)\s+(" + DEVA_NAME + r")"),
    re.compile(r"(?:कर्मचारी|श्रीमती|श्री|सहकर्मी)\s+(" + DEVA_NAME + r")"),
    re.compile(r"(?:धन्यवाद|सादर)[,।!]?[ \t]*\n+[ \t]*(" + DEVA_NAME + r")"),
    # Arabic
    re.compile(r"(?:اسمي|أنا)\s+(" + ARAB_NAME + r")"),
    re.compile(r"(?:الموظفة|الموظف|السيدة|السيد|زميلي|زميلتي)\s+(" + ARAB_NAME + r")"),
    re.compile(r"(?:مع التحية|مع خالص التحيات|وشكرا|شكرا)[^\n]*\n+[ \t]*(" + ARAB_NAME + r")"),
]

# Words the name patterns may pick up that are not names (kept unmasked).
NOT_NAMES = {
    "Payroll", "Support", "Team", "Hr", "Finance", "Payce", "Sir", "Madam", "Writing", "Facing",
    "Unable", "Not", "The", "Please", "Hai", "Hoon", "Ka", "Ki", "Ke", "Is", "Here", "Very",
    "है", "हूं", "हूँ", "का", "की", "के", "को", "भुगतान",
}

# Two or more capitalised Latin words in a row ("Ananya Iyer", "Rahul Singhania") are treated
# as a name once common words are trimmed from either end. Catches names mid-sentence that
# have no "my name is" or sign-off, without a list of known names.
CAP_RUN_RE = re.compile(r"(?<![A-Za-z])[A-Z][a-z]{2,}(?:[ \-][A-Z][a-z]{2,})+(?![A-Za-z])")
COMMON_CAPS = {
    # sentence starters and function words (English, Hinglish)
    "yesterday", "today", "tomorrow", "both", "our", "we", "can", "could", "please", "the", "this",
    "that", "these", "hi", "hello", "dear", "is", "are", "was", "and", "but", "also", "kindly", "why",
    "when", "what", "how", "who", "kal", "aaj", "maine", "humare", "hamare", "mera", "meri", "mere",
    "bhai", "namaste", "shukriya", "dhanyavaad", "regards", "thanks", "thank", "sincerely", "best",
    # payroll and product terms
    "payce", "support", "team", "payroll", "finance", "salary", "bonus", "payslip", "form", "employee",
    "staff", "manager", "leave", "encashment", "gratuity", "provident", "fund", "income", "tax",
    "professional", "account", "bank", "transfer", "email", "mail", "call", "phone", "mobile",
    "reference", "ticket", "statement", "letter", "offer", "joining", "reimbursement", "arrears",
    # places and calendar
    "india", "dubai", "abu", "dhabi", "sharjah", "uae", "emirates", "mumbai", "delhi", "bengaluru",
    "bangalore", "chennai", "pune", "hyderabad", "january", "february", "march", "april", "may",
    "june", "july", "august", "september", "october", "november", "december", "monday", "tuesday",
    "wednesday", "thursday", "friday", "saturday", "sunday",
}

PRIORITY = {"EMAIL": 0, "IBAN": 1, "EMIRATES_ID": 2, "AADHAAR": 3, "UAN": 3, "PAN": 4, "IFSC": 4,
            "PHONE": 5, "ACCOUNT": 6, "NAME": 7}


@dataclass
class MaskResult:
    text: str
    values: dict = field(default_factory=dict)   # token -> original value (for the vault only)
    counts: dict = field(default_factory=dict)   # type -> number of distinct values


@dataclass
class _Span:
    start: int
    end: int
    kind: str
    key: str          # what identifies "the same value" (digits only, or the person)


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s)


def _key(kind: str, value: str) -> str:
    """What makes two matches 'the same value' (so they share one token)."""
    if kind == "EMAIL":
        return value.lower()
    if kind in ("IBAN", "PAN", "IFSC"):
        return re.sub(r"\s", "", value).upper()
    if kind == "PHONE":
        return _digits(value)[-9:]
    return _digits(value)


def _last_pos(rx: re.Pattern, text: str) -> int:
    """Position of the last match of rx in text, or -1 (the nearest keyword decides the label)."""
    pos = -1
    for m in rx.finditer(text):
        pos = m.start()
    return pos


def _structured_spans(norm: str) -> list[_Span]:
    spans: list[_Span] = []
    for m in EMAIL_RE.finditer(norm):
        spans.append(_Span(m.start(), m.end(), "EMAIL", _key("EMAIL", m.group())))
    for m in IBAN_RE.finditer(norm):
        if iban_valid(m.group()):
            spans.append(_Span(m.start(), m.end(), "IBAN", _key("IBAN", m.group())))
    for m in EMIRATES_ID_RE.finditer(norm):
        d = _digits(m.group())
        spans.append(_Span(m.start(), m.end(), "EMIRATES_ID" if is_emirates_id(d) else "ACCOUNT", d))
    for m in TWELVE_RE.finditer(norm):
        d = _digits(m.group())
        before = norm[max(0, m.start() - 30):m.start()]
        if _last_pos(UAN_CONTEXT_RE, before) > _last_pos(AADHAAR_CONTEXT_RE, before):
            kind = "UAN"
        elif is_aadhaar(d):
            kind = "AADHAAR"
        else:
            kind = "ACCOUNT"
        spans.append(_Span(m.start(), m.end(), kind, d))
    for m in PAN_RE.finditer(norm):
        spans.append(_Span(m.start(), m.end(), "PAN", _key("PAN", m.group())))
    for m in IFSC_RE.finditer(norm):
        spans.append(_Span(m.start(), m.end(), "IFSC", _key("IFSC", m.group())))
    for rx in (PHONE_AE_RE, PHONE_IN_RE):
        for m in rx.finditer(norm):
            spans.append(_Span(m.start(), m.end(), "PHONE", _key("PHONE", m.group())))
    for m in LONG_NUMBER_RE.finditer(norm):
        spans.append(_Span(m.start(), m.end(), "ACCOUNT", m.group()))
    return spans


def _name_variants(sender_name: str | None, text: str,
                   extra_people: list[str] | None = None) -> list[tuple[str, str]]:
    """Return (name_string, person_key) pairs to search for, longest first."""
    people: list[str] = list(extra_people or [])
    if sender_name and sender_name.strip():
        people.append(" ".join(sender_name.split()))
    for rx in NAME_PATTERNS:
        for m in rx.finditer(text):
            words = [w for w in m.group(1).split() if w not in NOT_NAMES]
            if words:
                people.append(" ".join(words))
    for m in CAP_RUN_RE.finditer(text):
        words = re.split(r"[ \-]", m.group())
        while words and words[0].lower() in COMMON_CAPS:
            words.pop(0)
        while words and words[-1].lower() in COMMON_CAPS:
            words.pop()
        if len(words) >= 2 and not any(w.lower() in COMMON_CAPS for w in words):
            people.append(" ".join(words))
    variants: list[tuple[str, str]] = []
    seen: set[str] = set()
    for person in people:
        key = person.lower()
        for v in [person, *person.split()]:
            v = v.strip(".,;:!?")
            if len(v) >= 3 and v.lower() not in seen and v not in NOT_NAMES:
                seen.add(v.lower())
                variants.append((v, key))
    return sorted(variants, key=lambda x: -len(x[0]))


def _name_spans(text: str, sender_name: str | None, extra_people: list[str] | None = None) -> list[_Span]:
    spans: list[_Span] = []
    for name, person in _name_variants(sender_name, text, extra_people):
        if re.fullmatch(r"[A-Za-z\- ]+", name):
            rx = re.compile(r"(?<![A-Za-z])" + re.escape(name) + r"(?![a-z])", re.IGNORECASE)
        else:
            rx = re.compile(re.escape(name))   # Devanagari / Arabic: attached prefixes are allowed
        for m in rx.finditer(text):
            spans.append(_Span(m.start(), m.end(), "NAME", person))
    return spans


def _resolve(spans: list[_Span]) -> list[_Span]:
    """Keep non-overlapping spans: longest first, then by type priority."""
    chosen: list[_Span] = []
    for s in sorted(spans, key=lambda s: (-(s.end - s.start), PRIORITY[s.kind], s.start)):
        if all(s.end <= c.start or s.start >= c.end for c in chosen):
            chosen.append(s)
    return sorted(chosen, key=lambda s: s.start)


def mask_ticket(body: str, sender_name: str | None = None, sender_email: str | None = None,
                sender_phone: str | None = None) -> MaskResult:
    """Mask a ticket body. Sender email and phone are found by the recognisers when they
    appear in the body; the sender fields themselves are tokenised separately (HMAC)."""
    norm = normalize_digits(body)
    found = presidio_layer.analyze(norm)          # None when the Presidio layer is off
    if found is None:
        structured, people = _structured_spans(norm), []
    else:
        results, people = found
        structured = [_Span(r.start, r.end, r.entity_type, _key(r.entity_type, norm[r.start:r.end]))
                      for r in results]
    spans = _resolve(structured + _name_spans(norm, sender_name, people))

    tokens: dict[tuple[str, str], str] = {}
    counters: dict[str, int] = {}
    values: dict[str, str] = {}
    out, pos = [], 0
    for s in spans:
        ident = (s.kind, s.key)
        if ident not in tokens:
            counters[s.kind] = counters.get(s.kind, 0) + 1
            tokens[ident] = f"<{s.kind}_{counters[s.kind]}>"
            values[tokens[ident]] = body[s.start:s.end]
        out.append(body[pos:s.start])
        out.append(tokens[ident])
        pos = s.end
    out.append(body[pos:])
    return MaskResult(text="".join(out), values=values, counts=dict(counters))
