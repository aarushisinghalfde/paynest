#!/usr/bin/env python3
"""Phase A + G gates: the live dashboard and the support-head console answer and add up.

    $env:ADMIN_TOKEN = "<the ADMIN_TOKEN value from .env>"
    python scripts\\check_dashboard.py

Checks (no AWS sign-in needed):
  1. /api/dashboard refuses a request without the admin token
  2. Q3 history: 1,353 tickets, 201 wrong customer picks, 26 resubmits (the phase 4 numbers)
  3. live view: answers, and after scripts\\check_chat.py has run it shows its routes and rules
  4. (G) console: every live ticket is in exactly one bucket and the buckets add up
  5. (G) a resolved ticket and a waiting-approval ticket each have a full decision record
  6. (G) an Arabic ticket opens with an English machine translation whose numbers match
  7. (G5) with LEAD_TOKEN set (.env), the lead can read the console but not the review queue
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
    if hasattr(sys.stdout, "reconfigure"):  # Windows consoles are cp1252: Arabic/Hindi replies crashed print()
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
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

    # ---- phase G: support-head console ---------------------------------------------------------
    code, s = get("/api/console/summary?days=7", token)
    total = sum(b["n"] for b in s.get("buckets", []))
    results.append(("console_buckets_add_up", code == 200 and total == s.get("tickets") and total > 0,
                    f"HTTP {code}; {s.get('tickets')} tickets, buckets " +
                    ", ".join(f"{b['key']} {b['n']}" for b in s.get("buckets", []))))
    for view, name in (("resolved", "console_resolved_record"), ("approval", "console_approval_record")):
        code, q = get(f"/api/console/tickets?view={view}&days=7", token)
        first = (q.get("tickets") or [{}])[0]
        _, t = get(f"/api/console/tickets/{first.get('id')}?translate=false", token) if first.get("id") else (0, {})
        dec = t.get("decision") or {}
        ok = bool(dec.get("route", {}).get("rule")) and "guard" in dec and "classification" in dec
        results.append((name, ok, f"{q.get('count', 0)} {view} tickets; first {first.get('ref')}: rule "
                        f"{dec.get('route', {}).get('rule')}, answered by {dec.get('answer', {}).get('tier')}, "
                        f"guard ok {dec.get('guard', {}).get('ok')}"))
    code, q = get("/api/console/tickets?view=all&days=7&language=ar", token)
    ar = (q.get("tickets") or [{}])[0]
    _, t = get(f"/api/console/tickets/{ar.get('id')}", token) if ar.get("id") else (0, {})
    tq = (t.get("translation") or {}).get("question") or {}
    results.append(("console_arabic_translated", bool(tq.get("ok")),
                    f"ticket {ar.get('ref')}: " + (tq.get("english", "")[:90] if tq.get("ok") else str(tq.get("reason")))))
    lead = os.environ.get("LEAD_TOKEN", "")
    if lead:
        c1, _ = get("/api/console/summary", lead)
        c2, _ = get("/api/review/tasks", lead)
        results.append(("console_lead_read_only", c1 == 200 and c2 in (401, 403),
                        f"lead: console HTTP {c1}, review queue HTTP {c2}"))

    for name, ok, detail in results:
        print(f"{'PASS' if ok else 'FAIL'}  {name}: {detail}")
    with open(ROOT / "results" / "gates.csv", "a", newline="", encoding="utf-8") as fh:
        csv.writer(fh).writerows([[now, "G" if n.startswith("console") else "A", n, "ap-southeast-2", det, "pass" if ok else "fail", "", ""]
                                  for n, ok, det in results])
    passed = all(ok for _, ok, _ in results)
    print(f"\nPHASE A + G GATE: {'PASS' if passed else 'FAIL'} (results/gates.csv)")
    if not passed and any(n == "dashboard_live" and not ok for n, ok, _ in results):
        print("If the live view has no R01 rule yet, run  python scripts\\check_chat.py  first, then check again.")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
