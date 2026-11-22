"""Audit fixes (Q3 real-data check): how-to phrasing is a tie-breaker only; auto-route at 0.5."""

from agent.classifier import Classifier, SimilarTickets
from agent.nodes import Deps, classify

TRAIN = [
    ("Data migration from old payroll system How do we import last year's YTD figures from our previous vendor?", "Onboarding"),
    ("How do we bring opening balances from the previous payroll vendor during go-live?", "Onboarding"),
    ("Data migration: import YTD from old system before first payroll run", "Onboarding"),
    ("How do I download payslips for all employees at once?", "How-To"),
    ("Where can I download payslips in bulk as a zip?", "How-To"),
    ("How to add a new employee in Payce?", "How-To"),
    ("Salary not credited for employees this month, bank shows pending", "Payroll"),
    ("Payroll run stuck in approval for September", "Payroll"),
]


def _classify(text, classifier):
    return classify({"ticket_id": "t" * 32, "subject": "", "body": text}, Deps(None, None, b"k", classifier=classifier))


def _trained():
    sim = SimilarTickets(k=3)
    sim.fit([t for t, _ in TRAIN], [team for _, team in TRAIN])
    return Classifier(sim, None)


def test_how_to_phrasing_does_not_override_a_confident_other_team():
    out = _classify("How do we import last year's YTD figures from our previous payroll vendor?", _trained())
    assert out["team"] == "Onboarding"  # forcing How-To here was the 95.9% -> 86.3% regression


def test_how_to_phrasing_still_routes_real_how_to_questions():
    assert _classify("How do I download payslips for all employees?", _trained())["team"] == "How-To"
    assert _classify("How do I download payslips for all employees?", None)["team"] == "How-To"  # no data yet


def test_auto_route_threshold_is_point_five():
    c = _trained()
    assert c.auto_at == 0.5
    assert c.classify("Salary not credited for employees, bank shows pending")["branch"] == "auto"


def test_greetings_carry_no_team():
    out = classify({"ticket_id": "t" * 32, "subject": "", "body": "hi", "talk": "greeting"}, Deps(None, None, b"k"))
    assert out["team"] is None and out["classification"]["branch"] == "chat"
