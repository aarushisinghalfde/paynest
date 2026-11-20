"""Phase 3 gate: no raw value from the 60 seeded tickets survives masking."""
import json
import re
from pathlib import Path

import pytest

from pii import mask_ticket, presidio_layer
from pii.normalize import normalize_digits

FIXTURES = Path(__file__).parent / "fixtures"
SEED = json.loads((FIXTURES / "pii_seeded.json").read_text(encoding="utf-8"))
SEED_NER = json.loads((FIXTURES / "pii_seeded_ner.json").read_text(encoding="utf-8"))


def _forms(value: str) -> set[str]:
    """The raw value as it may appear: as written, without separators."""
    v = normalize_digits(value)
    forms = {v, re.sub(r"[\s\-]", "", v)}
    return {f for f in forms if len(f) >= 3}


def test_sixty_tickets_four_languages():
    assert len(SEED) == 60
    assert {t["language"] for t in SEED} == {"en", "hi-Latn", "hi", "ar"}


def _leaks(t):
    masked = mask_ticket(t["body"], sender_name=t["sender_name"]).text
    flat = re.sub(r"[\s\-]", "", normalize_digits(masked))
    leaks = [v for v in t["raw_values"] for f in _forms(v) if f in normalize_digits(masked) or
             (f.isalnum() and f.isascii() and len(f) >= 6 and f in flat)]
    return leaks, masked


@pytest.mark.parametrize("t", SEED, ids=[t["id"] for t in SEED])
def test_no_raw_value_leaks(t):
    """The gate: rules alone must mask every value (Presidio or not)."""
    leaks, masked = _leaks(t)
    assert not leaks, f"{t['id']} leaked {leaks}\n{masked}"


@pytest.mark.skipif(not presidio_layer.available(), reason="needs the Presidio layer")
@pytest.mark.parametrize("t", SEED_NER, ids=[t["id"] for t in SEED_NER])
def test_no_mid_sentence_name_leaks(t):
    """Names with no 'my name is' or sign-off: only spaCy NER can find these."""
    leaks, masked = _leaks(t)
    assert not leaks, f"{t['id']} leaked {leaks}\n{masked}"
