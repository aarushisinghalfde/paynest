"""Phase 9 gate: the output guard catches all 20 planted bad drafts and passes the 10 good ones."""

import json
from datetime import date
from pathlib import Path

import pytest

from agent import guard

CASES = json.loads((Path(__file__).parent / "fixtures" / "guard_cases.json").read_text(encoding="utf-8"))["cases"]


def _run(c):
    return guard.check(c["draft"], ticket_text=c["ticket_text"], region=c["region"], language=c["language"],
                       hits=c["hits"], facts=c["facts"], as_of=date.fromisoformat(c["as_of"]), ref=c["ref"])


@pytest.mark.parametrize("case", [c for c in CASES if c["expect"]], ids=lambda c: f"{c['id']}-{c['expect']}")
def test_bad_draft_is_caught_with_its_reason(case):
    r = _run(case)
    assert not r["ok"]
    assert any(p.split(":")[0] == case["expect"] for p in r["problems"]), r["problems"]


@pytest.mark.parametrize("case", [c for c in CASES if not c["expect"]], ids=lambda c: c["id"])
def test_good_draft_passes(case):
    assert _run(case) == {"ok": True, "problems": []}


def test_the_set_is_20_bad_and_10_good():
    assert sum(1 for c in CASES if c["expect"]) == 20 and sum(1 for c in CASES if not c["expect"]) == 10
