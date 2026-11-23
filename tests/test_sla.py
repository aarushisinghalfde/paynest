"""MSA Schedule 3: priority by the contract's definitions, deadlines by tier, the credit a miss would cost."""
from agent import risk, sla

KESTREL = {"tenant_id": "C-1001", "name": "Kestrel Logistics Pvt Ltd", "tier": "Enterprise", "monthly_fee_usd": 4200}


def _p(text):
    return sla.priority(text, risk.assess(text, "IN"))[0]


def test_priority_follows_the_contract_definitions():
    assert _p("We cannot run payroll, the run is stuck") == "P1"
    assert _p("Salary not credited to 3 employees") == "P1"
    assert _p("PF ECR filing due today and the upload fails") == "P1"
    assert _p("Net pay is wrong for 12 employees") == "P2"
    assert _p("How do I download payslips for all employees?") == "P3"


def test_the_customers_own_priority_is_never_lowered_silently():
    p, why = sla.priority("how do I add an employee", customer_pick="P1")
    assert p == "P1" and "we read P3" in why


def test_deadlines_and_the_credit_at_stake_come_from_the_tier():
    s = sla.assess(KESTREL, "P1", "2026-11-23T10:00:00+00:00")
    assert s["resolve_by"].startswith("2026-11-23T18:00") and s["respond_by"].startswith("2026-11-23T11:00")
    assert s["credit_usd"] == 420.0 and s["credit_usd_after_2x"] == 630.0
    assert sla.assess({**KESTREL, "tier": "Standard"}, "P1")["best_effort"]
    assert sla.state_of(s, False, "2026-11-23T17:00:00+00:00") == "at_risk"
    assert sla.state_of(s, False, "2026-11-23T19:00:00+00:00") == "breached"
