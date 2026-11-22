"""Presidio layer: one Presidio pipeline that runs our recognisers plus spaCy person names.

Our checksum-validated recognisers are registered in Presidio's registry as one custom
recogniser (PaynestRecognizer), next to Presidio's spaCy NER (model en_core_web_sm).
The NER finds names in the middle of a sentence that our phrase rules cannot, mainly in
English and Hinglish tickets.

Our recognisers stay the gate: with or without Presidio they return the same results, so
the 60-ticket leak test proves the same thing either way. Presidio only adds names.

PII_NER environment variable:
    auto      (default) use Presidio if it is installed, otherwise rules only (warns once)
    required  fail if Presidio or the spaCy model is missing (use in the worker image)
    off       rules only
"""
import logging
import os
import re

log = logging.getLogger(__name__)

SPACY_MODEL = "en_core_web_sm"
STRUCTURED = ["EMAIL", "IBAN", "EMIRATES_ID", "AADHAAR", "UAN", "PAN", "IFSC", "PHONE", "ACCOUNT"]

# Words spaCy may tag as PERSON in payroll tickets that are not people.
NOT_PEOPLE = {
    "aadhaar", "pan", "uan", "iban", "ifsc", "pf", "epf", "tds", "hr", "wps", "gratuity", "payce",
    "payslip", "payroll", "salary", "form", "emirates", "namaste", "bhai", "hi", "hello", "dear",
    "team", "sir", "madam", "regards", "thanks", "please", "kindly", "october", "november", "ji",
    "shukriya", "dhanyavaad", "kal", "maine", "humare", "mera", "meri", "arrears", "ctc", "bonus",
}
NOT_PEOPLE |= {"email", "mail", "call", "phone", "mobile", "account", "bank", "again", "other",
               "reference", "ticket", "leave", "employee", "manager", "statement", "letter", "contact"}
# Payce screens, menus and buttons. spaCy tags a capitalised button name as a PERSON
# ("choose Download as ZIP"), which turned help-article steps into "[name removed]".
NOT_PEOPLE |= {
    "open", "go", "click", "select", "choose", "pick", "save", "submit", "add", "edit", "delete", "remove",
    "upload", "download", "export", "import", "settings", "reports", "report", "audit", "trail", "users",
    "user", "roles", "role", "permissions", "dashboard", "home", "menu", "admin", "payslips", "employees",
    "people", "policies", "policy", "attendance", "approvals", "approve", "run", "runs", "new", "next",
    "back", "filter", "search", "view", "zip", "pdf", "csv", "excel", "integrations", "billing", "invoices",
}

_analyzer = None
_tried = False


class AnalyzerUnavailable(RuntimeError):
    pass


def _build():
    from presidio_analyzer import AnalyzerEngine, EntityRecognizer, RecognizerResult
    from presidio_analyzer.nlp_engine import NlpEngineProvider

    from pii.masker import _structured_spans
    from pii.normalize import normalize_digits

    class PaynestRecognizer(EntityRecognizer):
        """Our regex + checksum recognisers, as one Presidio recogniser."""

        def load(self):
            pass

        def analyze(self, text, entities, nlp_artifacts=None):
            return [RecognizerResult(s.kind, s.start, s.end, 1.0)
                    for s in _structured_spans(normalize_digits(text)) if s.kind in entities]

    provider = NlpEngineProvider(nlp_configuration={
        "nlp_engine_name": "spacy",
        "models": [{"lang_code": "en", "model_name": SPACY_MODEL}],   # never the 600 MB default
    })
    engine = AnalyzerEngine(nlp_engine=provider.create_engine(), supported_languages=["en"])
    engine.registry.add_recognizer(
        PaynestRecognizer(supported_entities=STRUCTURED, name="PaynestRecognizer", supported_language="en"))
    return engine


def get_analyzer():
    """The shared AnalyzerEngine, or None when the layer is off or not installed."""
    global _analyzer, _tried
    mode = os.environ.get("PII_NER", "auto").lower()
    if mode == "off":
        return None
    if not _tried:
        _tried = True
        try:
            _analyzer = _build()
        except Exception as exc:  # ImportError, or OSError when the spaCy model is missing
            if mode == "required":
                raise AnalyzerUnavailable(f"PII_NER=required but Presidio is unavailable: {exc}") from exc
            log.warning("Presidio layer unavailable (%s); masking with rules only", exc)
    if _analyzer is None and mode == "required":
        raise AnalyzerUnavailable("PII_NER=required but Presidio is unavailable")
    return _analyzer


def set_analyzer(analyzer) -> None:
    """For tests: use this analyzer (or None) instead of building one."""
    global _analyzer, _tried
    _analyzer, _tried = analyzer, True


def available() -> bool:
    try:
        return get_analyzer() is not None
    except AnalyzerUnavailable:
        return False


def analyze(norm_text: str):
    """Run the whole pipeline. Returns (structured results, person names) or None."""
    analyzer = get_analyzer()
    if analyzer is None:
        return None
    results = analyzer.analyze(text=norm_text, language="en", entities=STRUCTURED + ["PERSON"])
    structured = [r for r in results if r.entity_type in STRUCTURED]
    people = []
    if re.search(r"[A-Za-z]", norm_text):
        for r in results:
            if r.entity_type == "PERSON":
                name = _clean_person(norm_text[r.start:r.end])
                if name:
                    people.append(name)
    return structured, people


def _clean_person(value: str) -> str | None:
    """Keep Latin-script, capitalised words that are not payroll terms or acronyms."""
    value = re.sub(r"'s$", "", value.strip())
    words = [w.strip(".,;:!?()") for w in value.split()]
    words = [w for w in words if re.fullmatch(r"[A-Z][a-z]+(?:-[A-Z][a-z]+)?", w)
             and w.lower() not in NOT_PEOPLE]
    return " ".join(words) if words else None
