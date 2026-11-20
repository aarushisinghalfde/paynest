"""Phase 4: IDs are masked by FORMAT, even when the checksum fails (typos are still PII).

All values below are invented for this test; none come from the client data.
"""
import pytest

from pii import mask_ticket

CASES = [
    # (text, raw value, expected token kind)
    ("PAN QWERT5521Z please verify", "QWERT5521Z", "PAN"),                   # 4th letter not a holder type
    ("My Aadhaar is 0000 4821 7734 thanks", "0000 4821 7734", "AADHAAR"),   # starts with 0, bad Verhoeff
    ("Aadhaar: 1111 2222 3334 attached", "1111 2222 3334", "AADHAAR"),
    ("Emirates ID 784-0000-1234567-0 for him", "784-0000-1234567-0", "EMIRATES_ID"),   # bad Luhn
    ("IBAN AE00 0000 1111 2222 3333 444 please", "AE00 0000 1111 2222 3333 444", "IBAN"),  # bad mod-97
    ("Salary IBAN SA00 0000 1111 2222 3333 4444", "SA00 0000 1111 2222 3333 4444", "IBAN"),
]


@pytest.mark.parametrize("text,value,kind", CASES)
def test_invalid_checksum_ids_are_masked_and_labelled(text, value, kind):
    r = mask_ticket(text)
    assert value not in r.text
    token = next(t for t, v in r.values.items() if v == value)
    assert token.startswith(f"<{kind}_")


def test_twelve_digits_without_context_or_checksum_is_still_masked_as_account():
    r = mask_ticket("Reference 0000 4821 7734 from the bank")
    assert "0000 4821 7734" not in r.text and "<ACCOUNT_1>" in r.text


def test_iban_like_text_from_unknown_country_needs_a_valid_checksum():
    """Not every 'XX00 ...' string is an IBAN: unknown countries still need mod-97."""
    text = "Code ZZ00 0000 1111 2222 3333 444 is our internal batch"
    assert "ZZ00" in mask_ticket(text).text


def test_lowercase_or_embedded_codes_are_not_pans():
    for text in ("order abcde1234f shipped", "SKU XABCDE1234FX"):
        assert mask_ticket(text).text == text
