#!/usr/bin/env python3
"""Send real (masked) Q3 questions through the LIVE chat, so the control room fills with fresh tickets.

    python scripts\\seed_live.py                 # 60 questions, every team and language, plus an outage burst
    python scripts\\seed_live.py --n 200         # the whole labelled set (about 10 minutes)

Questions come from evals/local/labelled_set_v1.json (already masked: no personal data is sent). Each
goes to a customer of the same region, spread across Enterprise, Business and Standard so the SLA
deadlines differ. Writes results/seed_<time>.json: ticket refs and outcomes only, never text.
"""
import argparse
import collections
import json
import random
import sys
import time
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
API = "https://whps24ardd.execute-api.ap-southeast-2.amazonaws.com/api"
TENANTS = {"IN": ["C-1001", "C-1002", "C-1005", "C-1013", "C-1014", "C-1031", "C-1032"],
           "UAE": ["C-1003", "C-1004", "C-1015", "C-1017", "C-1037", "C-1038"]}
DONE = {"replied", "waiting_review", "taken_over", "failed"}


def call(method: str, path: str, body: dict | None = None) -> dict:
    req = urllib.request.Request(API + path, method=method, data=json.dumps(body).encode() if body else None,
                                 headers={"Content-Type": "application/json", "Idempotency-Key": str(uuid.uuid4())})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def pick(items: list[dict], n: int) -> list[dict]:
    """Round-robin over (team, language) so small groups (Arabic, Statutory) are always in."""
    groups = collections.defaultdict(list)
    for t in items:
        groups[(t["data_label"], t["language"])].append(t)
    for g in groups.values():
        random.Random(7).shuffle(g)
    out, keys = [], sorted(groups)
    while len(out) < n and any(groups[k] for k in keys):
        for k in keys:
            if groups[k] and len(out) < n:
                out.append(groups[k].pop())
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=60)
    ap.add_argument("--no-burst", action="store_true", help="skip the 5-report outage burst")
    args = ap.parse_args()
    items = json.loads((ROOT / "evals" / "local" / "labelled_set_v1.json").read_text(encoding="utf-8"))
    chosen = pick(items, args.n)
    print(f"API {call('GET', '/health').get('version')}: sending {len(chosen)} questions ...")
    sent, rr = [], collections.Counter()
    for t in chosen:
        region = t.get("tenant_region") or "IN"
        tenant = TENANTS[region][rr[region] % len(TENANTS[region])]
        rr[region] += 1
        text = f"{t.get('subject') or ''}. {t.get('body') or ''}".strip(". ")
        r = call("POST", "/tickets", {"tenant_id": tenant, "body": text, "channel": "chat",
                                      "conversation_id": str(uuid.uuid4())})
        sent.append({"ref": t["ticket_ref"], "team": t["data_label"], "language": t["language"], "tenant": tenant,
                     "ticket_id": r["ticket_id"]})
        time.sleep(1.0)
    if not args.no_burst:  # five reports of the same outage from one customer within a minute
        for i in range(5):
            r = call("POST", "/tickets", {"tenant_id": "C-1002", "channel": "chat", "conversation_id": str(uuid.uuid4()),
                                          "body": f"Payslip PDF download fails with an error for all users (report {i + 1})"})
            sent.append({"ref": f"burst-{i + 1}", "team": "Integration", "language": "en", "tenant": "C-1002",
                         "ticket_id": r["ticket_id"]})
            time.sleep(2)
    print("Waiting for the agent ...")
    deadline = time.time() + 300
    while time.time() < deadline:
        for s in sent:
            if s.get("status") in DONE:
                continue
            t = call("GET", f"/tickets/{s['ticket_id']}")
            s.update(status=t.get("agent_status"), route=t.get("route"), replies=len(t.get("replies") or []))
        if all(s.get("status") in DONE for s in sent):
            break
        time.sleep(5)
    by = collections.Counter((s.get("route"), s.get("status")) for s in sent)
    print("\nroute / status                    tickets")
    for (route, status), n in by.most_common():
        print(f"  {str(route):12} {str(status):18} {n}")
    team = collections.defaultdict(collections.Counter)
    for s in sent:
        team[s["team"]]["answered" if s.get("status") == "replied" and s.get("route") == "reply" else
                        "with a person" if s.get("status") in ("waiting_review", "taken_over") else
                        s.get("route") or "pending"] += 1
    print("\nby team (Q3 label):")
    for k, c in sorted(team.items()):
        print(f"  {k:20} {dict(c)}")
    out = ROOT / "results" / f"seed_{time.strftime('%Y%m%d-%H%M')}.json"
    out.write_text(json.dumps([{k: v for k, v in s.items()} for s in sent], indent=1), encoding="utf-8")
    print(f"\nWrote {out.relative_to(ROOT)} (refs and outcomes only). Open the control room to see them.")
    if any(s.get("status") not in DONE for s in sent):
        sys.exit(f"{sum(s.get('status') not in DONE for s in sent)} tickets still not finished after 5 minutes")


if __name__ == "__main__":
    main()
