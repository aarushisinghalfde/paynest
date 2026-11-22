#!/usr/bin/env python3
"""Phase A gate: the live operations dashboard answers and shows the right numbers.

    $env:ADMIN_TOKEN = "<the ADMIN_TOKEN value from .env>"
    python scripts\\check_dashboard.py

Checks (no AWS sign-in needed):
  1. /api/dashboard refuses a request without the admin token
  2. Q3 history: 1,353 tickets, 201 wrong customer picks, 26 resubmits (the phase 4 numbers)
  3. live view: answers, and after scripts\\check_chat.py has run it shows its routes and rules
Appends the results to results/gates.csv.
"""

import csv
import datetime as dt
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
URL = "https://whps24ardd.execute-api.ap-southeast-2.amazonaws.com"


def get(path, token=None):
    req = urllib.request.Request(URL + path, headers={"X-Admin-Token": token} if token else {})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310 - the demo URL
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, {}


def main() -> int:
    token = os.environ.get("ADMIN_TOKEN", "")
    if not token:
        print('Set the token first:  $env:ADMIN_TOKEN = "<ADMIN_TOKEN value from .env>"')
        return 2
    now = dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat()
    results = []

    code, _ = get("/api/dashboard?scope=live")
    results.append(("dashboard_needs_token", code in (401, 403), f"no token -> HTTP {code}"))

    code, d = get("/api/dashboard?scope=export", token)
    c, m = d.get("classification", {}), d.get("merges", {})
    ok = code == 200 and d.get("tickets") == 1353 and c.get("customer_pick_wrong") == 201 and m.get("resubmits") == 26
    results.append(("dashboard_q3_history", ok, f"HTTP {code}; tickets {d.get('tickets')}, wrong picks "
                    f"{c.get('customer_pick_wrong')}, resubmits {m.get('resubmits')} (want 1353, 201, 26)"))

    code, d = get("/api/dashboard?scope=live&days=7", token)
    rules = {r["key"] for r in d.get("by_rule", [])}
    res = d.get("resolution", {})
    ok = code == 200 and d.get("tickets", 0) > 0 and "R01-injection" in rules
    results.append(("dashboard_live", ok, f"HTTP {code}; {d.get('tickets')} tickets, rules {sorted(rules)[:6]}, "
                    f"auto-answered {res.get('answered_automatically')}, How-To rate {res.get('howto_automation_rate')}"))

    for name, ok, detail in results:
        print(f"{'PASS' if ok else 'FAIL'}  {name}: {detail}")
    with open(ROOT / "results" / "gates.csv", "a", newline="", encoding="utf-8") as fh:
        csv.writer(fh).writerows([[now, "A", n, "ap-southeast-2", det, "pass" if ok else "fail", "", ""]
                                  for n, ok, det in results])
    passed = all(ok for _, ok, _ in results)
    print(f"\nPHASE A GATE: {'PASS' if passed else 'FAIL'} (results/gates.csv)")
    if not passed and any(n == "dashboard_live" and not ok for n, ok, _ in results):
        print("If the live view has no R01 rule yet, run  python scripts\\check_chat.py  first, then check again.")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
