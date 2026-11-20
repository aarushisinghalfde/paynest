"""Single first names (no surname, no 'my name is') and the cost: ordinary text untouched.

Names here are deliberately NOT in scripts/make_pii_seed.py, so these tests do not just
repeat the seed data.
"""
import pytest

from pii import mask_ticket
from pii.masker import _name_variants

SINGLE_NAMES = [
    # first-name list, no cue at all
    ("Gaurav will send the revised payslip tomorrow.", "Gaurav"),
    ("The arrears for Ishita are still pending.", "Ishita"),
    ("Fahad has not received the WPS salary.", "Fahad"),
    # context cues, names that are in no list
    ("Please ask Tenzin about the bonus.", "Tenzin"),
    ("Gurleen confirmed the bank change last week.", "Gurleen"),
    ("Kal Zubair ne bola ki salary aa jayegi.", "Zubair"),
    ("Bhavesh's reimbursement was rejected.", "Bhavesh"),
    # Hindi and Arabic, first-name list
    ("सुरेश को वेतन पर्ची नहीं मिली।", "सुरेश"),
    ("يرجى التواصل مع سلطان بخصوص الراتب.", "سلطان"),
    ("أرسلت الطلب لخالد أمس.", "خالد"),
]

NOT_NAMES = [
    "Please contact Support about the October payroll.",
    "Thanks Team, the Company ne salary late bheji.",
    "Form ka status kya hai? Aadhaar ka update ho gaya.",
    "Ask Finance why the TDS doubled; HR said it is a system issue.",
    "Our Dubai office uses WPS and Emirates ID for onboarding.",
    "The bonus was approved by the Department in March.",
    "मेरा भविष्य निधि खाता अपडेट नहीं हुआ और वेतन का हिसाब गलत है।",
    "कृपया इस महीने की सीमा बताएं, विजय दिवस की छुट्टी भी जोड़ें।",
    "الحمد لله تم استلام الراتب، عيد مبارك للجميع.",
    "ما هو عمر الموظف المطلوب للمكافأة؟ الطلب صالح حتى نهاية الشهر.",
    "يرجى إرسال شهادة الراتب عليه ختم الشركة.",
]


@pytest.mark.parametrize("text,name", SINGLE_NAMES)
def test_single_first_name_is_masked(text, name):
    assert name not in mask_ticket(text).text


@pytest.mark.parametrize("text", NOT_NAMES)
def test_ordinary_text_is_untouched(text):
    assert mask_ticket(text).text == text


def test_first_name_shares_token_with_full_name():
    r = mask_ticket("Ishita Rao joined in May. Later Ishita said the PF is missing.")
    assert r.text == "<NAME_1> joined in May. Later <NAME_1> said the PF is missing."


def test_arabic_prefix_kept_and_name_masked():
    r = mask_ticket("أرسلت الطلب لخالد وخالد لم يرد.")
    assert r.text == "أرسلت الطلب ل<NAME_1> و<NAME_1> لم يرد."


def test_name_inside_a_longer_word_is_not_a_match():
    assert not any(v == "علي" for v, _ in _name_variants(None, "يرجى إرسال شهادة الراتب عليه ختم."))
