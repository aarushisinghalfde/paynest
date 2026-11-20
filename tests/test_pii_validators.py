"""One unit test (or more) per recogniser and validator."""
from pii import mask_ticket
from pii.normalize import normalize_digits
from pii.validators import (
    iban_valid,
    is_aadhaar,
    is_emirates_id,
    luhn_valid,
    verhoeff_check_digit,
    verhoeff_valid,
)


def test_normalise_digits_keeps_length():
    for native in ("٧٨٤١٩٩٠", "۷۸۴۱۹۹۰", "७८४१९९०"):
        out = normalize_digits(native)
        assert out == "7841990" and len(out) == len(native)


def test_verhoeff():
    base = "23456789012"
    full = base + verhoeff_check_digit(base)
    assert verhoeff_valid(full)
    wrong = full[:-1] + str((int(full[-1]) + 1) % 10)
    assert not verhoeff_valid(wrong)


def test_aadhaar_rules():
    base = "23456789012"
    good = base + verhoeff_check_digit(base)
    assert is_aadhaar(good)
    assert not is_aadhaar("1" + good[1:])          # cannot start with 0 or 1
    assert not is_aadhaar(good[:-1])               # 11 digits


def test_luhn_and_emirates_id():
    assert luhn_valid("79927398713")
    assert not luhn_valid("79927398710")
    assert is_emirates_id("784198012345674") == luhn_valid("784198012345674")
    assert not is_emirates_id("123198012345674")   # must start with 784


def test_iban_mod97():
    assert iban_valid("GB82 WEST 1234 5698 7654 32")
    assert iban_valid("AE070331234567890123456")
    assert not iban_valid("AE070331234567890123457")


def test_pan_ifsc_uan():
    r = mask_ticket("PAN ABCPS1234K, IFSC HDFC0001234, UAN 100123456789")
    assert "<PAN_1>" in r.text and "<IFSC_1>" in r.text and "<UAN_1>" in r.text


def test_phones_and_email():
    r = mask_ticket("Call +91 98765 43210 or +971 50 123 4567 or mail a.b@x.co.in")
    assert r.counts == {"PHONE": 2, "EMAIL": 1}


def test_unknown_long_number_is_masked():
    r = mask_ticket("Reference 123456789012345678")
    assert "123456789012345678" not in r.text


def test_names_in_three_scripts():
    assert "Rahul" not in mask_ticket("My name is Rahul Sharma").text
    assert "प्रिया" not in mask_ticket("मेरा नाम प्रिया वर्मा है").text
    assert "مريم" not in mask_ticket("اسمي مريم الهاشمي").text


def test_same_value_same_token():
    r = mask_ticket("Email a@b.com, again a@b.com, other c@d.com")
    assert r.text == "Email <EMAIL_1>, again <EMAIL_1>, other <EMAIL_2>"


def test_native_digits_masked_in_original():
    r = mask_ticket("هاتفي ٠٥٠١٢٣٤٥٦٧")
    assert r.text == "هاتفي <PHONE_1>" and r.values["<PHONE_1>"] == "٠٥٠١٢٣٤٥٦٧"


def test_plain_payroll_words_untouched():
    text = "Salary for October 2026 was 45000 INR, form 16 pending."
    assert mask_ticket(text).text == text


def test_aadhaar_after_uan_keeps_its_label():
    base = "23456789012"
    a = base + verhoeff_check_digit(base)
    r = mask_ticket(f"UAN 100123456789. Aadhaar {a}.")
    assert r.text == "UAN <UAN_1>. Aadhaar <AADHAAR_1>."
