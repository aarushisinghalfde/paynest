#!/usr/bin/env python3
"""Write the latest result of every gate into docs/PROJECT_STATE.md (the Evidence section).

    python scripts\\evidence.py          (run_checks.ps1 runs it at the end)

Reads results/gates.csv (every check script appends to it) and results/evals.json, keeps the most
recent row per gate, and rewrites only the block between the evidence markers. Nothing else in the
file changes, so the evidence is never hand-typed and never stale.
"""

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "docs" / "PROJECT_STATE.md"
START, END = "<!-- evidence:start -->", "<!-- evidence:end -->"
PHASES = {"0": "0 Foundations", "1": "1 Infra", "2": "2 Intake", "3": "3 PII", "4": "4 Data", "5": "5 Agent",
          "6": "6 Classify", "7": "7 Dedupe/incident", "8": "8 Chat", "9": "9 Safety", "A": "A Dashboard",
          "B": "B Knowledge", "C": "C Evals", "D": "D Operate", "E": "E AgentCore", "G": "G Console"}


def latest(rows: list[dict]) -> list[dict]:
    """Most recent row per (phase, gate); India/UAE placeholder rows are history, not evidence."""
    keep = {}
    for r in rows:
        if r.get("region") in ("ap-south-1", "me-central-1"):
            continue
        keep[(r["phase"], r["gate"])] = r  # file is append-only, so the last row wins
    order = list(PHASES)
    return sorted(keep.values(), key=lambda r: (order.index(r["phase"]) if r["phase"] in order else 99, r["gate"]))


def render(rows: list[dict], evals: dict | None) -> str:
    passed = sum(r["result"] == "pass" for r in rows)
    out = [START, "", f"Latest result of each gate ({passed}/{len(rows)} passing), written by `scripts/evidence.py` "
           "from `results/gates.csv`.", "", "| Phase | Gate | Result | When (UTC) | Detail |", "|---|---|---|---|---|"]
    for r in rows:
        detail = (r.get("value") or "").replace("|", "/").replace("\n", " ")[:140]
        mark = "PASS" if r["result"] == "pass" else "**FAIL**"
        out.append(f"| {PHASES.get(r['phase'], r['phase'])} | {r['gate']} | {mark} | {r['timestamp'][:16]} | {detail} |")
    if evals:
        ls = evals.get("labelled_set") or {}
        c = ls.get("classification") or {}
        f = ls.get("faithfulness") or {}
        out += ["", f"Evals ({evals.get('generated_at', '')[:16]}): classification {c.get('accuracy')} on "
                f"{ls.get('n')} labelled tickets (customer pick {c.get('customer_pick')}), macro-F1 {c.get('macro_f1')}"
                + (f"; faithfulness {f.get('score')} over {f.get('claims')} claims in {f.get('drafts_judged')} model drafts"
                   if f else "; faithfulness not run (needs `--with-model`)") + "."]
    out += ["", END]
    return "\n".join(out)


def main() -> int:
    gates = ROOT / "results" / "gates.csv"
    if not gates.exists():
        print("results/gates.csv not found: run the checks first")
        return 1
    with open(gates, encoding="utf-8") as fh:
        rows = latest([r for r in csv.DictReader(fh) if r.get("gate")])
    ev_path = ROOT / "results" / "evals.json"
    evals = json.loads(ev_path.read_text(encoding="utf-8")) if ev_path.exists() else None
    block = render(rows, evals)
    text = STATE.read_text(encoding="utf-8")
    if START in text and END in text:
        text = text[: text.index(START)] + block + text[text.index(END) + len(END):]
    else:
        text = text.rstrip() + "\n\n## Evidence\n\n" + block + "\n"
    STATE.write_text(text, encoding="utf-8")
    failing = [r["gate"] for r in rows if r["result"] != "pass"]
    print(f"Evidence: {len(rows) - len(failing)}/{len(rows)} gates passing -> docs/PROJECT_STATE.md"
          + (f"; failing: {', '.join(failing)}" if failing else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
