#!/usr/bin/env python3
"""Measure the PII gate: recall per type and language, over-masking, latency.

    python scripts/eval_pii.py                      # seeded fixtures
    python scripts/eval_pii.py --file real.json     # same format: id, language, body, raw_values, ...
    python scripts/eval_pii.py --record             # also append summary rows to results/gates.csv

Recall: share of raw values that no longer appear after masking, per inferred type
(email, IBAN, Emirates ID, Aadhaar, PAN, IFSC, phone, account, name) and per language.
Over-masking: (1) clean sentences changed by masking, (2) masked spans that match no
listed raw value (false positives on the labelled tickets).
Latency: p50 and p95 per ticket, with the NER layer in use (presidio or rules).

Prints counts and kinds only. Writes results/phase3_pii_eval.json (no ticket text).
"""
import argparse
import csv
import datetime as dt
import json
import re
import statistics
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pii import mask_ticket, presidio_layer  # noqa: E402
from pii.normalize import normalize_digits  # noqa: E402
from pii.validators import IFSC_RE, PAN_RE, iban_valid, is_aadhaar, is_emirates_id  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures"
OUT = ROOT / "results" / "phase3_pii_eval.json"
GATES = ROOT / "results" / "gates.csv"


def infer_type(value: str) -> str:
    v = normalize_digits(value).strip()
    sq = re.sub(r"[\s\-]", "", v)
    if "@" in v:
        return "EMAIL"
    if iban_valid(sq):
        return "IBAN"
    if sq.isdigit():
        if is_emirates_id(sq):
            return "EMIRATES_ID"
        if len(sq) == 12 and is_aadhaar(sq):
            return "AADHAAR"
        if len(sq) == 12:
            return "UAN"
        if 10 <= len(sq) <= 13 and re.fullmatch(r"(?:91|971|0)?[5-9]\d{8,9}", sq):
            return "PHONE"
        return "ACCOUNT"
    if sq.startswith("+") and sq[1:].isdigit():
        return "PHONE"
    if PAN_RE.fullmatch(sq):
        return "PAN"
    if IFSC_RE.fullmatch(sq):
        return "IFSC"
    return "NAME"


def leaked(value: str, masked: str) -> bool:
    v = normalize_digits(value)
    m = normalize_digits(masked)
    if v in m:
        return True
    sq = re.sub(r"[\s\-]", "", v)
    return sq.isascii() and sq.isalnum() and len(sq) >= 6 and sq in re.sub(r"[\s\-]", "", m)


def matches_label(found: str, raw_values: list[str]) -> bool:
    f = re.sub(r"[\s\-]", "", normalize_digits(found)).lower()
    for raw in raw_values:
        r = re.sub(r"[\s\-]", "", normalize_digits(raw)).lower()
        if f == r or f in r or r in f:
            return True
    return False


def _rates(counts: dict) -> dict:
    return {k: {"recall": round(m / n, 4), "n": n} for k, (m, n) in sorted(counts.items())}


def _p95(timings: list[float]) -> float | None:
    return round(sorted(timings)[max(0, int(len(timings) * 0.95) - 1)], 2) if timings else None


def evaluate(tickets: list[dict], clean: list[str]) -> dict:
    by_type = defaultdict(lambda: [0, 0])     # type -> [masked, total]
    by_lang = defaultdict(lambda: [0, 0])
    timings, false_pos, spans, leaked_kinds = [], 0, 0, defaultdict(int)
    for t in tickets:
        t0 = time.perf_counter()
        r = mask_ticket(t["body"], sender_name=t.get("sender_name"))
        timings.append((time.perf_counter() - t0) * 1000)
        for value in t["raw_values"]:
            kind = infer_type(value)
            ok = not leaked(value, r.text)
            by_type[kind][0] += ok
            by_type[kind][1] += 1
            by_lang[t["language"]][0] += ok
            by_lang[t["language"]][1] += 1
            if not ok:
                leaked_kinds[kind] += 1
        for found in r.values.values():
            spans += 1
            false_pos += not matches_label(found, t["raw_values"])
    changed = sum(mask_ticket(s).text != s for s in clean)
    total = sum(n for _, n in by_type.values())
    caught = sum(m for m, _ in by_type.values())
    return {
        "ner_layer": "presidio" if presidio_layer.available() else "rules",
        "tickets": len(tickets),
        "values": total,
        "recall": round(caught / total, 4) if total else None,
        "recall_by_type": _rates(by_type),
        "recall_by_language": _rates(by_lang),
        "leaked_by_type": dict(leaked_kinds),
        "masked_spans": spans,
        "false_positive_spans": false_pos,
        "false_positive_rate": round(false_pos / spans, 4) if spans else 0.0,
        "clean_sentences": len(clean),
        "clean_sentences_changed": changed,
        "latency_ms_p50": round(statistics.median(timings), 2) if timings else None,
        "latency_ms_p95": _p95(timings),
    }


def record(summary: dict) -> None:
    try:
        commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
                                cwd=ROOT).stdout.strip()
    except OSError:
        commit = ""
    now = dt.datetime.now(dt.UTC).isoformat(timespec="seconds")
    rows = [
        ("pii_eval_recall", f"{summary['recall']:.2%} of {summary['values']} values ({summary['ner_layer']})",
         summary["recall"] == 1.0),
        ("pii_eval_overmasking", f"{summary['clean_sentences_changed']}/{summary['clean_sentences']} clean "
         f"sentences changed; {summary['false_positive_rate']:.1%} unlabelled spans",
         summary["clean_sentences_changed"] == 0),
        ("pii_eval_latency", f"p50 {summary['latency_ms_p50']} ms, p95 {summary['latency_ms_p95']} ms", True),
    ]
    with open(GATES, "a", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        for gate, value, ok in rows:
            w.writerow([now, 3, gate, "local", value, "pass" if ok else "fail", commit, ""])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--file", action="append", type=Path,
                    help="labelled tickets JSON (default: the seeded fixtures)")
    ap.add_argument("--clean", type=Path, default=FIXTURES / "pii_clean.json",
                    help="JSON list of sentences with no personal data")
    ap.add_argument("--record", action="store_true", help="append rows to results/gates.csv")
    args = ap.parse_args()

    files = args.file or [FIXTURES / "pii_seeded.json", FIXTURES / "pii_seeded_ner.json"]
    tickets = [t for f in files for t in json.loads(f.read_text(encoding="utf-8"))]
    clean = json.loads(args.clean.read_text(encoding="utf-8"))
    summary = evaluate(tickets, clean)

    OUT.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"NER layer: {summary['ner_layer']}   tickets: {summary['tickets']}   values: {summary['values']}")
    print(f"recall: {summary['recall']:.2%}")
    for k, v in summary["recall_by_type"].items():
        print(f"  {k:<12} {v['recall']:.2%}  (n={v['n']})")
    for k, v in summary["recall_by_language"].items():
        print(f"  {k:<12} {v['recall']:.2%}  (n={v['n']})")
    print(f"over-masking: {summary['clean_sentences_changed']}/{summary['clean_sentences']} clean sentences "
          f"changed; {summary['false_positive_spans']}/{summary['masked_spans']} masked spans unlabelled")
    print(f"latency: p50 {summary['latency_ms_p50']} ms, p95 {summary['latency_ms_p95']} ms")
    print(f"wrote {OUT.relative_to(ROOT)}")
    if args.record:
        record(summary)
        print(f"appended 3 rows to {GATES.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
