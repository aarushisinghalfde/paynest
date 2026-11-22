"""Phase 7 / plan v2 phase C: duplicates and incidents (fixes from the Q3 replay)."""
from datetime import UTC, datetime, timedelta

from agent import dedupe as dd
from agent.dedupe import Recent
from agent.similarity import RESUBMIT_MARKER, concepts, same_issue, shingles

T0 = datetime(2026, 9, 25, 4, 30, tzinfo=UTC)
A = "Payslip PDF is blank / shows net pay 0. I opened my payslip for September and the PDF is blank with net pay 0."
B = "Cannot download my payslip. Downloading my payslip gives a PDF with zero values. Salary was credited."
C = "Payslip blank aa rahi hai. Meri payslip ka PDF blank aa raha hai aur net pay 0 dikha raha hai."
REPORT = "Report blank aa rahi hai. Monthly salary register ka report download karne pe blank file aa rahi hai."
HOWTO = "How do I download payslips for all employees as a PDF?"


def _r(i, text, minutes):
    return Recent(f"t{i}", f"PN-{i}", T0 + timedelta(minutes=minutes), text)


def test_template_follow_up_about_something_else_is_not_a_resubmit():
    # Q3: "Following up on the refund promised last month" is sent by many customers (2 wrong duplicates)
    assert not RESUBMIT_MARKER.search("Refund status. Following up on the refund promised last month.")
    assert RESUBMIT_MARKER.search("Following up on my earlier ticket PN-100802, no reply yet.")
    assert RESUBMIT_MARKER.search("RE: Question on PF wage ceiling")
    recent = [_r(1, "Refund status. Following up on the refund promised last month. Please confirm status.", 0)]
    dup, _ = dd.find_duplicate(recent[0].text, T0 + timedelta(hours=1), recent)
    assert dup is None


def test_explicit_reference_is_a_duplicate():
    recent = [_r(1, "Payroll run stuck at processing", 0)]
    assert dd.find_duplicate("Following up on my earlier ticket PN-1, no reply yet.", T0 + timedelta(hours=2),
                             recent)[0] == "PN-1"


def test_same_outage_in_other_words_and_languages_is_one_issue():
    for x, y in ((A, B), (A, C), (B, C)):
        assert same_issue(x, shingles(x), y, shingles(y)) >= dd.INCIDENT_THRESHOLD, (x, y)


def test_shared_subject_alone_or_generic_words_are_not_the_same_issue():
    assert same_issue(A, shingles(A), HOWTO, shingles(HOWTO)) < dd.INCIDENT_THRESHOLD  # payslip, no symptom
    assert same_issue(B, shingles(B), REPORT, shingles(REPORT)) < dd.INCIDENT_THRESHOLD  # blank report, no payslip
    assert concepts("API token returns 401") == {"api_auth"}


def test_mixed_wording_burst_opens_one_incident_and_later_tickets_attach():
    recent, opened = [], []
    texts = [A, B, C, A, B, A, C, B, A, B]
    for i, text in enumerate(texts):
        now = T0 + timedelta(minutes=5 * i)
        inc = dd.find_incident(text, now, recent, opened)
        r = Recent(f"t{i}", f"PN-{i}", now, text)
        if inc.get("opened"):
            opened.append({"id": inc["incident_id"], "signature": inc["signature"], "opened_at": now})
            for x in recent:
                if x.id in inc["members"]:
                    x.incident_id = inc["incident_id"]
        if inc:
            r.incident_id = inc["incident_id"]
        recent.append(r)
    assert len(opened) == 1
    assert sum(1 for r in recent if r.incident_id) == len(texts)

