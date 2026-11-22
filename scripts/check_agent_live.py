#!/usr/bin/env python3
"""Live gates for phases 6, 7 and 9 (plan v2 phase C): the deployed agent, through the public URL.

    python scripts\\check_agent_live.py            (no AWS sign-in needed)

phase 6  classify_live      7 messages in 4 languages reach the right team (>= 6 of 7; the labelled-set
                            eval in run_evals.py is the full measure)
phase 7  duplicate_live     the same problem sent again with "RE:" is linked as a duplicate, no new work
phase 7  incident_live      5 reports of the same outage from one tenant in a few seconds: the 5th
                            is handled as part of one incident
phase 9  pii_never_sent     a question carrying a PAN and a phone number: stored masked, reply has neither
phase 9  statutory_review   a statutory figure asked as a how-to waits for a person, nothing sent

Creates real test tickets in the demo database (tenant C-1004, the burst uses a random tag so
repeated runs open a fresh incident). Appends to results/gates.csv.
"""

import argparse
import csv
import datetime as dt
import re
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_chat import URL, run_case  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

CLASSIFY = [
    ("C-1001", "Salary not credited for 14 employees this month, the bank shows pending", "Payroll"),
    ("C-1001", "Leave balance was not carried forward for 12 employees after year end", "Leave & Attendance"),
    ("C-1001", "SSO login loop: users are sent back to the login page after signing in", "Access / Login"),
    ("C-1001", "Our integration API token returns 401 since yesterday", "Integration"),
    ("C-1001", "Is mahine salary credit nahi hui 20 logon ki, bank pending dikha raha hai", "Payroll"),
    ("C-1001", "छुट्टी का बैलेंस गलत दिख रहा है, कृपया ठीक करें", "Leave & Attendance"),
    ("C-1003", "كيف يتم احتساب مكافأة نهاية الخدمة للموظف الذي أكمل ثلاث سنوات؟", "Statutory"),
]
PAN, PHONE = "ABCPK1234F", "9876543210"


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=URL)
    base = ap.parse_args().url.rstrip("/")
    results = []

    def gate(name, fn):
        try:
            ok, detail = fn()
        except Exception as exc:  # noqa: BLE001
            ok, detail = False, f"{type(exc).__name__}: {exc}"[:220]
        results.append((name, ok, detail))
        print(f"{'PASS' if ok else 'FAIL'}  {name}: {detail}")

    def classify_live():
        got = []
        for tenant, text, want in CLASSIFY:
            _, t = run_case(base, tenant, text)
            got.append((want, t.get("team")))
        right = sum(w == g for w, g in got)
        wrong = [f"{w}->{g}" for w, g in got if w != g]
        return right >= len(CLASSIFY) - 1, f"{right}/{len(CLASSIFY)} to the right team; wrong: {wrong or 'none'}"

    def duplicate_live():
        tag = uuid.uuid4().hex[:6]
        text = f"Bank file for the October payroll was rejected with code BF{tag}, 31 employees affected"
        _, first = run_case(base, "C-1004", text)
        _, again = run_case(base, "C-1004", f"RE: {text}. Still waiting, please check.")
        ok = again.get("route") == "duplicate"
        return ok, f"first: {first.get('route')}; resubmit: {again.get('route')} ({(again.get('route_reason') or '')[:80]})"

    def incident_live():
        tag = uuid.uuid4().hex[:6]
        text = f"Payslip PDF shows net pay 0 for everyone since this morning (ref {tag})"
        routes = [run_case(base, "C-1004", text)[1].get("route") for _ in range(5)]
        return routes[-1] == "incident", f"routes: {routes}"

    def pii_never_sent():
        _, t = run_case(base, "C-1001", f"My PAN is {PAN} and my phone is {PHONE}. How do I download payslips "
                                         f"for all employees?")
        reply = " ".join(r["body"] for r in t.get("replies") or [])
        stored = t.get("masked_body") or ""
        leaked = [v for v in (PAN, PHONE) if v in reply or v in stored]
        masked = bool(re.search(r"<PAN_\d+>", stored)) and bool(re.search(r"<PHONE_\d+>", stored))
        return not leaked and masked and bool(reply), (f"stored masked: {masked}; leaked: {leaked or 'none'}; "
                                                      f"replied: {bool(reply)}")

    def statutory_review():
        _, t = run_case(base, "C-1001", "How do I see the PF wage ceiling for September 2026?")
        ok = t.get("route") == "review" and t.get("agent_status") == "waiting_review" and not t.get("replies")
        return ok, f"team {t.get('team')}, route {t.get('route')}, {t.get('agent_status')}"

    gate("phase6_classify_live", classify_live)
    gate("phase7_duplicate_live", duplicate_live)
    gate("phase7_incident_live", incident_live)
    gate("phase9_pii_never_sent", pii_never_sent)
    gate("phase9_statutory_review", statutory_review)

    now = dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat()
    with open(ROOT / "results" / "gates.csv", "a", newline="", encoding="utf-8") as fh:
        csv.writer(fh).writerows([[now, n.split("_")[0].replace("phase", ""), n, "ap-southeast-2", d,
                                   "pass" if ok else "fail", "", ""] for n, ok, d in results])
    passed = all(ok for _, ok, _ in results)
    print(f"\nPHASES 6/7/9 LIVE GATE: {'PASS' if passed else 'FAIL'} (results/gates.csv)")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
