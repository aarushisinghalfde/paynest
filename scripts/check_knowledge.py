#!/usr/bin/env python3
"""Phase B gate: an imported article reaches the How-To agent through the database.

    $env:ADMIN_TOKEN = "<the ADMIN_TOKEN value from .env>"
    python scripts\\check_knowledge.py

1. imports a clearly marked test article (KB-GATE-1) that contains an email address
2. the import is listed, with the email masked
3. waits for the worker to reload (up to ~2 min), then asks the chat the article's question:
   the reply must contain the article's steps
4. withdraws the article (the gate leaves nothing behind)
Appends to results/gates.csv. No AWS sign-in needed.
"""

import csv
import datetime as dt
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
URL = "https://whps24ardd.execute-api.ap-southeast-2.amazonaws.com"
STEP = "Open Reports > Audit trail and choose Export (gate check)"
ARTICLE = f"""---
id: KB-GATE-1
title: Exporting the audit trail (gate test article)
region: ALL
language: en
---
To export the audit trail:

1. {STEP}.
2. Pick the date range.

Questions: gate.check@example.com
"""


def call(method, path, body=None, token=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["X-Admin-Token"] = token
    if method == "POST" and path.startswith("/api/tickets"):
        headers["Idempotency-Key"] = uuid.uuid4().hex
    req = urllib.request.Request(URL + path, data=json.dumps(body).encode() if body is not None else None,
                                 method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310 - the demo URL
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}") if e.headers.get("content-type", "").startswith("application/json") else {}


def ask(question):
    code, out = call("POST", "/api/tickets", {"tenant_id": "C-1001", "body": question, "channel": "chat",
                                              "conversation_id": f"gate-{uuid.uuid4().hex[:12]}"})
    if code not in (200, 201, 202):
        return f"POST HTTP {code}"
    for _ in range(30):
        time.sleep(2)
        _, t = call("GET", f"/api/tickets/{out['ticket_id']}")
        if t.get("replies"):
            return " ".join(r["body"] for r in t["replies"])
    return "(no reply in 60 s)"


def main() -> int:
    token = os.environ.get("ADMIN_TOKEN", "")
    if not token:
        print('Set the token first:  $env:ADMIN_TOKEN = "<ADMIN_TOKEN value from .env>"')
        return 2
    results = []
    code, out = call("POST", "/api/knowledge", {"articles": [{"filename": "KB-GATE-1.md", "text": ARTICLE}],
                                                 "imported_by": "check_knowledge"}, token)
    arts = out.get("articles") or [{}]
    results.append(("knowledge_import", code == 200 and arts[0].get("kb_id") == "KB-GATE-1",
                    f"HTTP {code}; {arts[0]}"))
    code, listing = call("GET", "/api/knowledge", token=token)
    row = next((a for a in listing.get("articles", []) if a["kb_id"] == "KB-GATE-1"), {})
    results.append(("knowledge_masked", bool(row) and (row.get("masked_counts") or {}).get("EMAIL") == 1,
                    f"listed {bool(row)}; masked {row.get('masked_counts')}"))
    reply, ok = "", False
    for attempt in range(4):  # the worker reloads knowledge at most once a minute
        if attempt:
            time.sleep(35)
        reply = ask("How do I export the audit trail?")
        if STEP in reply:
            ok = True
            break
    results.append(("knowledge_used_by_agent", ok and "example.com" not in reply, f"reply: {reply[:160]!r}"))
    code, _ = call("DELETE", "/api/knowledge/KB-GATE-1", token=token)
    results.append(("knowledge_withdraw", code == 200, f"HTTP {code}"))

    now = dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat()
    for name, ok, detail in results:
        print(f"{'PASS' if ok else 'FAIL'}  {name}: {detail}")
    with open(ROOT / "results" / "gates.csv", "a", newline="", encoding="utf-8") as fh:
        csv.writer(fh).writerows([[now, "B", n, "ap-southeast-2", d, "pass" if ok else "fail", "", ""]
                                  for n, ok, d in results])
    passed = all(ok for _, ok, _ in results)
    print(f"\nPHASE B GATE: {'PASS' if passed else 'FAIL'} (results/gates.csv)")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
