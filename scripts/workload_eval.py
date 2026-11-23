#!/usr/bin/env python3
"""Can the agent carry 30% of the support workload? Measured on the 200 labelled Q3 tickets, weighted
by the real Q3 mix (1,353 tickets), through the real agent graph (no model: the floor).

    python scripts\\workload_eval.py                         # ..\\paynest-support-discovery\\data-room
    python scripts\\workload_eval.py --data-room <path> --record

Each ticket ends in one of three places; what is left for a person is a share of its handling time:
  resolved by the agent ............ 5%  (spot checks; pessimistic 25%)
  a person approves a ready draft .. 35% (read, check the source, approve; pessimistic 60%)
  a person does the work ........... 85% (the agent already masked, classified, translated, routed,
                                          set the priority and deadline, and replied with what happens next)
Handling minutes per team are assumptions (MINUTES below); replace them with the client's handle times.
Two runs: "day one" (only the guides) and "after learning" (in time order, support writes each new How-To
answer once in Review; every later similar question is answered from it, as in production).
Gate: workload_reduction >= 30% in the pessimistic case after learning (the headcount goal).
"""
import argparse
import collections
import csv
import json
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent import console, knowledge_import, labelled_eval  # noqa: E402
from agent.retrieval import Retriever  # noqa: E402
from agent.runner import MemoryCheckpoints, run  # noqa: E402
from loader import labelled  # noqa: E402
from scripts.run_evals import read_data_room  # noqa: E402

MINUTES = {"How-To": 10, "Access / Login": 10, "Reports": 15, "Leave & Attendance": 15, "Billing": 15,
           "Onboarding": 20, "Statutory": 25, "Integration": 40, "Payroll": 40}
LEFT = {"resolved": (0.05, 0.25), "draft": (0.35, 0.60), "person": (0.85, 0.85), "merged": (0.10, 0.10)}
GATE = 0.30


def outcome(row, st) -> str:  # noqa: D103
    b = console.bucket(row)
    if b in ("resolved", "merged"):
        return b
    if b == "approval" and st.get("draft_mode") in ("fallback", "model", "cache"):
        return "draft"
    return "person"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-room", default=str(ROOT.parent / "paynest-support-discovery" / "data-room"))
    ap.add_argument("--record", action="store_true", help="append the gate to results/gates.csv")
    args = ap.parse_args()
    ds = labelled_eval.build_dataset(read_data_room(Path(args.data_room)))
    chosen = labelled.stratified(ds.tables["tickets"], n=200)
    held = {t["ticket_ref"] for t in chosen}
    regions = {t["tenant_id"]: t["region"] for t in ds.tables["tenants"]}
    examples = [{"question": t["masked_body"], "kb_id": t["kb_ids"][0], "region": regions.get(t["tenant_id"])}
                for t in ds.tables["tickets"] if t["ticket_ref"] not in held and t.get("kb_ids") and t.get("masked_body")]

    def fresh():
        store, deps = labelled_eval._deps(ds, held)
        store.kb = list(ds.tables["kb_chunks"])
        knowledge_import.demo_guides(store)  # as the demo worker does; real articles replace them
        deps.retriever = Retriever(store.knowledge()[0], ds.tables["statutory_rules"], examples=examples)
        return store, deps

    results = {}
    for mode in ("day one", "after learning"):
        store, deps = fresh()
        done = []
        for t in sorted(chosen, key=lambda t: str(t["created_at"])):
            text = f"{t['subject_masked'] or ''}. {t['masked_body'] or ''}".strip(". ")
            tid = store.create(t["tenant_id"], "chat", text, None)
            store.save_progress(tid, conversation_id=f"wl-{uuid.uuid4().hex[:12]}", created_at=t["created_at"])
            done.append((t["team"], tid, run(tid, deps, MemoryCheckpoints())))
            if mode == "after learning":  # support writes each new How-To answer once (counted as person work)
                for task in [x for x in store.list_reviews() if x["kind"] == "knowledge"]:
                    store.decide_review(task["id"], "approve", "1. Open the screen for this task.\n2. Follow the steps.",
                                        "support")
                    deps.retriever = Retriever(store.knowledge()[0], ds.tables["statutory_rules"], examples=examples)
        rows = {r["id"]: r for r in store.console_rows()}
        per = collections.defaultdict(collections.Counter)
        for team, tid, st in done:
            per[team][outcome(rows[tid], st)] += 1
        results[mode] = per
    per_team = results["after learning"]
    q3 = collections.Counter(t["team"] for t in ds.tables["tickets"] if t.get("team"))
    total = sum(q3.values())

    def reduction(case: int) -> float:
        before = after = 0.0
        for team, share in q3.items():
            c = per_team.get(team)
            if not c:
                continue
            left = sum(LEFT[k][case] * n for k, n in c.items()) / sum(c.values())
            before += share * MINUTES.get(team, 20)
            after += share * MINUTES.get(team, 20) * left
        return 1 - after / before

    untouched = sum(q3[team] / total * c["resolved"] / sum(c.values()) for team, c in per_team.items())
    day1 = results["day one"]
    saved, per_team = per_team, day1
    d1 = (reduction(0), reduction(1))
    per_team = saved
    expected, pessimistic = reduction(0), reduction(1)
    print(f"day one (guides only): {d1[0]:.1%} expected, {d1[1]:.1%} pessimistic")
    print(f"{'team':20} {'Q3 share':>8}  resolved  draft  person  merged")
    for team, share in q3.most_common():
        c = per_team.get(team, collections.Counter())
        print(f"{team:20} {share / total:8.0%}  {c['resolved']:8}  {c['draft']:5}  {c['person']:6}  {c['merged']:6}")
    print(f"\nQ3 tickets no person touches: {untouched:.0%}")
    print(f"workload reduction: {expected:.1%} expected, {pessimistic:.1%} pessimistic (gate {GATE:.0%})")
    ok = pessimistic >= GATE
    detail = f"{pessimistic:.1%} pessimistic, {expected:.1%} expected; {untouched:.0%} of Q3 tickets untouched"
    print(f"{'PASS' if ok else 'FAIL'} workload_reduction: {detail}")
    (ROOT / "results" / "workload.json").write_text(json.dumps(
        {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "per_team": {k: dict(v) for k, v in per_team.items()},
         "q3_mix": dict(q3), "minutes": MINUTES, "left": LEFT, "expected": expected, "pessimistic": pessimistic,
         "untouched": untouched}, indent=1), encoding="utf-8")
    if args.record:
        with open(ROOT / "results" / "gates.csv", "a", newline="", encoding="utf-8") as fh:
            csv.writer(fh).writerow([time.strftime("%Y-%m-%dT%H:%M:%S"), "C", "workload_reduction", "local", detail,
                                     "pass" if ok else "fail", "", ""])
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
