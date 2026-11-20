#!/usr/bin/env python3
"""Phase 6 model-fit test: which classifier is good enough, cheapest first.

    python scripts\\model_fit.py                         # evals/local/labelled_set_v1.json
    python scripts\\model_fit.py --record                # also append gate rows to results/gates.csv

Candidates: keywords only; keywords + similar tickets (leave-one-out over the set); each
model rung in config/models.yaml through the same structured-output schema. For each:
accuracy, macro-F1, accuracy per language, Payroll vs Statutory confusion, p95 latency,
cost per 1,000 tickets. Gate (build plan): the lowest rung with >= 90% overall and no
language below 85% becomes the default; the customer's own pick is the baseline to beat.
Only masked text is sent to a model. Needs OPENROUTER_API_KEY in .env for the model rungs.
"""

import argparse
import csv
import datetime as dt
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent import keywords, metrics  # noqa: E402
from agent.classifier import TEAM_LIST, SimilarTickets, system_prompt, validate  # noqa: E402
from agent.models import ModelClient  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
GATE_OVERALL, GATE_LANGUAGE = 0.90, 0.85


def label_of(row):
    return row.get("final_label") or row["data_label"]


def evaluate(name, rows, preds, ms=None, cost=0.0):
    gold = [label_of(r) for r in rows]
    langs = [r["language"] for r in rows]
    per_lang = metrics.by_group(gold, preds, langs)
    acc = metrics.accuracy(gold, preds)
    return {
        "candidate": name,
        "n": len(rows),
        "accuracy": round(acc, 4),
        "macro_f1": round(metrics.macro_f1(gold, preds, TEAM_LIST), 4),
        "by_language": per_lang,
        "payroll_vs_statutory": metrics.confusion_between(gold, preds, "Payroll", "Statutory"),
        "p95_ms": round(metrics.p95(ms), 1) if ms else None,
        "cost_per_1000_usd": round(cost / len(rows) * 1000, 4) if rows else None,
        "passes": acc >= GATE_OVERALL and min(per_lang.values()) >= GATE_LANGUAGE,
    }


def leave_one_out_similar(rows):
    preds = []
    for i, r in enumerate(rows):
        others = rows[:i] + rows[i + 1 :]
        sim = SimilarTickets(k=5).fit(
            [f"{o['subject']} {o['body']}" for o in others], [label_of(o) for o in others]
        )
        preds.append(sim.predict(f"{r['subject']} {r['body']}")["team"])
    return preds


def run_model(rows, client, rung):
    preds, ms, cost, broken = [], [], 0.0, 0
    for r in rows:
        try:
            res = client.json_call(
                system_prompt(), f"{r['subject']}\n{r['body']}", rung=rung, purpose="model_fit"
            )
            preds.append(validate(res.data)["team"])
            ms.append(res.ms)
            cost += res.cost_usd
        except Exception:  # noqa: BLE001 - a broken answer counts as wrong
            preds.append(None)
            broken += 1
        time.sleep(0.2)
    return preds, ms, cost, broken


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", type=Path, default=ROOT / "evals" / "local" / "labelled_set_v1.json")
    ap.add_argument("--record", action="store_true")
    ap.add_argument("--no-models", action="store_true", help="only the free candidates")
    args = ap.parse_args()
    rows = json.loads(args.set.read_text(encoding="utf-8"))
    results = [evaluate("customer pick (baseline)", rows, [r["customer_pick"] for r in rows])]
    results.append(
        evaluate("keywords", rows, [keywords.classify(f"{r['subject']} {r['body']}")["team"] for r in rows])
    )
    results.append(evaluate("keywords + similar tickets", rows, leave_one_out_similar(rows)))
    if not args.no_models:
        from shared import settings  # noqa: F401 - loads .env

        client = ModelClient(cap_usd=1.0)
        for rung, model in enumerate(client.ladder):
            preds, ms, cost, broken = run_model(rows, client, rung)
            res = evaluate(f"rung {rung}: {model}", rows, preds, ms, cost)
            res["broken_answers"] = broken
            results.append(res)
    winner = next((r for r in results[1:] if r["passes"]), None)
    out = {
        "set": str(args.set.name),
        "gate": {"overall": GATE_OVERALL, "per_language": GATE_LANGUAGE},
        "results": results,
        "default": winner["candidate"] if winner else None,
    }
    (ROOT / "results" / "model_fit.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"{'candidate':46} {'acc':>6} {'F1':>6} {'min lang':>9} {'p95 ms':>8} {'$/1000':>8}  pass")
    for r in results:
        print(
            f"{r['candidate'][:46]:46} {r['accuracy']:6.1%} {r['macro_f1']:6.3f} {min(r['by_language'].values()):9.1%} "
            f"{r['p95_ms'] or '-':>8} {r['cost_per_1000_usd'] if r['cost_per_1000_usd'] is not None else '-':>8}  "
            f"{'yes' if r['passes'] else 'no'}"
        )
    print(
        f"default classifier: {out['default'] or 'none passes: low-confidence tickets go to the triage desk'}"
    )
    if args.record:
        now = dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat()
        with open(ROOT / "results" / "gates.csv", "a", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            base = results[0]["accuracy"]
            w.writerow(
                [
                    now,
                    6,
                    "model_fit_default",
                    "local",
                    out["default"] or "none",
                    "pass" if winner else "fail",
                    "",
                    ";".join(r["candidate"] for r in results if r["candidate"].startswith("rung")),
                ]
            )
            if winner:
                w.writerow(
                    [
                        now,
                        6,
                        "beats_customer_baseline",
                        "local",
                        f"{winner['accuracy']:.1%} vs {base:.1%}",
                        "pass" if winner["accuracy"] > base else "fail",
                        "",
                        "",
                    ]
                )
    return 0 if winner else 1


if __name__ == "__main__":
    sys.exit(main())
