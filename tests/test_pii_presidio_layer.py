"""Presidio layer: wiring tests with a fake analyzer (always run) and real-Presidio tests
(run where presidio-analyzer and en_core_web_sm are installed, e.g. CI and the image)."""
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from pii import mask_ticket, presidio_layer
from pii.masker import _structured_spans
from pii.normalize import normalize_digits

SEED = json.loads((Path(__file__).parent / "fixtures" / "pii_seeded.json").read_text(encoding="utf-8"))
needs_presidio = pytest.mark.skipif(not presidio_layer.available(),
                                     reason="presidio-analyzer / en_core_web_sm not installed")


class FakeAnalyzer:
    """Behaves like the real pipeline: our recognisers + PERSON for the given names."""

    def __init__(self, people):
        self.people = people

    def analyze(self, text, language, entities):
        out = [SimpleNamespace(entity_type=s.kind, start=s.start, end=s.end, score=1.0)
               for s in _structured_spans(text)]
        for name in self.people:
            for m in re.finditer(re.escape(name), text):
                out.append(SimpleNamespace(entity_type="PERSON", start=m.start(), end=m.end(), score=0.85))
        return out


@pytest.fixture
def fake():
    saved = (presidio_layer._analyzer, presidio_layer._tried)
    yield lambda people: presidio_layer.set_analyzer(FakeAnalyzer(people))
    presidio_layer._analyzer, presidio_layer._tried = saved


def test_ner_name_mid_sentence_is_masked_everywhere(fake):
    fake(["Ananya Iyer"])
    r = mask_ticket("Yesterday I spoke with Ananya Iyer and Ananya said it is fixed.")
    assert r.text == "Yesterday I spoke with <NAME_1> and <NAME_1> said it is fixed."


def test_ner_payroll_terms_and_acronyms_are_not_names(fake):
    fake(["TDS", "Payslip", "Form"])
    text = "Payslip shows TDS twice and Form 16 is missing."
    assert mask_ticket(text).text == text


def test_same_tokens_with_and_without_presidio(fake):
    for t in SEED:
        presidio_layer.set_analyzer(None)
        rules_only = mask_ticket(t["body"], sender_name=t["sender_name"]).text
        fake([])
        assert mask_ticket(t["body"], sender_name=t["sender_name"]).text == rules_only, t["id"]


def test_required_mode_fails_loudly(monkeypatch):
    saved = (presidio_layer._analyzer, presidio_layer._tried)
    presidio_layer.set_analyzer(None)
    monkeypatch.setenv("PII_NER", "required")
    with pytest.raises(presidio_layer.AnalyzerUnavailable):
        presidio_layer.get_analyzer()
    presidio_layer._analyzer, presidio_layer._tried = saved


def test_off_mode_skips_presidio(monkeypatch, fake):
    fake(["Ananya"])
    monkeypatch.setenv("PII_NER", "off")
    assert presidio_layer.get_analyzer() is None


@needs_presidio
def test_real_pipeline_matches_our_recognisers():
    for t in SEED:
        norm = normalize_digits(t["body"])
        results, _ = presidio_layer.analyze(norm)
        got = sorted((r.start, r.end, r.entity_type) for r in results)
        want = sorted((s.start, s.end, s.kind) for s in _structured_spans(norm))
        assert got == want, t["id"]


@needs_presidio
def test_real_spacy_finds_a_mid_sentence_name():
    r = mask_ticket("Yesterday I spoke with Priya Nair from finance about the bonus.")
    assert "Priya" not in r.text and "Nair" not in r.text
