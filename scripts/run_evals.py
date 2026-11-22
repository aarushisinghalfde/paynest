#!/usr/bin/env python3
"""Plan v2 phase C: evals on the 200-ticket labelled set and the Q3 replay, from your laptop.

    python scripts\\run_evals.py                                   # ..\\paynest-support-discovery\\data-room
    python scripts\\run_evals.py --data-room <path> --record       # also append gate rows to results/gates.csv

Everything runs locally on masked text (the data room is masked in memory, as the loader does);
no model is called, so the numbers are the agent's floor without the model leg.
The 200 tickets are the same stratified set the loader saves (same seed). The similar-tickets
classifier and the past-resolution examples are trained on the OTHER Q3 tickets, so no ticket
grades itself. Each of the 200 then goes through the real agent graph (PII gate -> classify ->
dedupe -> route -> draft -> output guard -> send) in an in-memory store.

Writes results/evals.json. Gates:
  classify_accuracy      >= 90% overall and >= 85% in every language (the model-fit gate);
                         the customer's own pick is the baseline to beat
  statutory_never_auto   no ticket labelled Statutory gets an answer without a person
  sent_replies_clean     0 PII / unknown tokens in anything sent
  guard_pass_rate        >= 95% of drafts pass the output guard
  dedupe_precision       >= 95% (Q3 replay)
  meridian_incident      the 25 Sep burst is 1 incident, opened by ticket 5 at the latest
"""

import argparse
import csv
import datetime as dt
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent import labelled_eval  # noqa: E402
from agent.replay import gates as replay_gates  # noqa: E402
from agent.replay import replay  # noqa: E402


def read_data_room(path: Path) -> dict[str, str]:
    return {("data-room/" + p.relative_to(path).as_posix()): p.read_text(encoding="utf-8")
            for p in path.rglob("*") if p.is_file() and p.suffix in (".json", ".csv", ".md")}


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-room", type=Path, default=ROOT.parent / "paynest-support-discovery" / "data-room")
    ap.add_argument("--record", action="store_true", help="append the gates to results/gates.csv")
    args = ap.parse_args()
    if not args.data_room.is_dir():
        print(f"data room not found: {args.data_room} (pass --data-room)")
        return 2

    t0 = time.time()
    ds = labelled_eval.build_dataset(read_data_room(args.data_room.resolve()))
    print(f"masked {len(ds.tables['tickets'])} Q3 tickets in memory ({time.time() - t0:.0f} s)")
    ev = labelled_eval.evaluate(ds)
    rp = replay(ds.tables["tickets"], ds.tables["jira_issues"])
    gates = labelled_eval.gates(ev) + replay_gates(rp)[:2]

    out = {"generated_at": dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat(), "labelled_set": ev,
           "replay": rp, "gates": [{"gate": n, "pass": ok, "detail": d} for n, ok, d in gates]}
    (ROOT / "results").mkdir(exist_ok=True)
    (ROOT / "results" / "evals.json").write_text(json.dumps(out, indent=2, ensure_ascii=False, default=str),
                                                 encoding="utf-8")

    c = ev["classification"]
    print(f"\nclassification on {ev['n']} labelled tickets (agent, no model):")
    print(f"  accuracy {c['accuracy']:.1%}  macro-F1 {c['macro_f1']:.3f}  customer pick {c['customer_pick']:.1%}")
    print(f"  by language: {c['by_language']}")
    print(f"  auto-routed {c['auto_share']:.0%} at {c['auto_accuracy']:.1%};  Payroll/Statutory mix-ups "
          f"{c['payroll_vs_statutory']}")
    print(f"routes: {ev['routes']}")
    print(f"answer tiers: {ev['answer_tiers']}")
    print()
    for name, ok, detail in gates:
        print(f"{'PASS' if ok else 'FAIL'}  {name}: {detail}")
    passed = all(ok for _, ok, _ in gates)
    print(f"\nPHASE C GATE: {'PASS' if passed else 'FAIL'} (results/evals.json)")
    if args.record:
        now = out["generated_at"]
        with open(ROOT / "results" / "gates.csv", "a", newline="", encoding="utf-8") as fh:
            csv.writer(fh).writerows([[now, "C", n, "local", d, "pass" if ok else "fail", "", ""] for n, ok, d in gates])
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
