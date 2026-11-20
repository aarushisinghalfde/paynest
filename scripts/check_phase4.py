#!/usr/bin/env python3
"""Phase 4 gate: the loaded data in RDS is complete, routed, dated and leak-free.

Run after scripts/run_phase4.py, from the repo root:

    $env:AWS_PROFILE = "payce-fde"
    python scripts\\check_phase4.py --data-room ..\\paynest-support-discovery\\data-room

The checks run ON THE EC2 (`loader verify`), reading every table back from Postgres:
  ticket_count            1,353 unique tickets (1,367 rows minus 14 repeated)
  tenants_tagged          every tenant has a home region; every ticket's tenant exists
  routing_tables          demo table -> Sydney; production table -> ap-south-1 / me-central-1
  timestamps_utc          every ticket has a UTC creation time
  leak_scan_all_tables    0 raw values (found independently in the raw files) in any table
  pf_wage_ceiling_by_date old rule before 1 Aug, new rule from 1 Aug (retrieval and get_rate)
  wps_file_format_by_date old rule before 15 Jul, new rule from 15 Jul
plus, on this laptop:
  labelled_set_saved      200 tickets, every team and language, in evals/local/
Appends one row per check to results/gates.csv. Exit code 0 only if all pass.
"""

import argparse
import csv
import datetime as dt
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts import phase4_remote as remote  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LABELLED = ROOT / "evals" / "local" / "labelled_set_v1.json"


def labelled_gate() -> tuple[bool, str]:
    if not LABELLED.exists():
        return False, "evals/local/labelled_set_v1.json missing: run scripts/run_phase4.py first"
    rows = json.loads(LABELLED.read_text(encoding="utf-8"))
    teams = {r["data_label"] for r in rows}
    langs = {r["language"] for r in rows}
    ok = len(rows) == 200 and len(teams) == 9 and langs == {"en", "hi", "hi-Latn", "ar"}
    return ok, f"{len(rows)} tickets, {len(teams)} teams, languages {sorted(langs)}; relabel pending"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--data-room", type=Path, default=ROOT.parent / "paynest-support-discovery" / "data-room")
    args = ap.parse_args()
    remote.check_account()
    data, _ = remote.zip_data_room(args.data_room.resolve())
    get_url, _ = remote.upload_and_presign(data, want_put=False)
    result = remote.run_loader("verify", get_url, None)
    if "error" in result:
        print(f"VERIFY FAILED: {result['error']}")
        return 1
    rows = [(g["gate"], g["pass"], g["detail"]) for g in result["gates"]]
    rows.append(("labelled_set_saved", *labelled_gate()))
    now = dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat()
    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except Exception:  # noqa: BLE001
        commit = ""
    with open(ROOT / "results" / "gates.csv", "a", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        for gate, ok, detail in rows:
            print(f"{'PASS' if ok else 'FAIL'}  {gate}: {detail}")
            w.writerow([now, 4, gate, remote.REGION, detail[:200], "pass" if ok else "fail", commit, ""])
    print(f"\nrows in RDS: {result['rows']}")
    all_ok = all(ok for _, ok, _ in rows)
    print(f"\nPHASE 4 GATE: {'PASS' if all_ok else 'FAIL'} (results/gates.csv)")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
