#!/usr/bin/env python3
"""Phase D gate: one ticket -> one X-Ray trace with a span per graph node.

    $env:AWS_PROFILE = "payce-fde"; python scripts\\check_traces.py

Posts one chat message to the demo, waits for the agent, then asks X-Ray for the trace whose
annotation ticket_id is that ticket (X-Ray takes up to a minute or two to index it). Needs the
iam and ec2 stacks updated for phase D (collector + xray permissions). Appends to results/gates.csv.
"""

import csv
import datetime as dt
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_chat import URL, run_case  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
REGION = "ap-southeast-2"


def node_names(trace: dict) -> list[str]:
    """Every span name in an X-Ray trace (segments and nested subsegments)."""
    names = []

    def walk(seg):
        names.append(seg.get("name"))
        for sub in seg.get("subsegments") or []:
            walk(sub)

    for s in trace.get("Segments") or []:
        walk(json.loads(s["Document"]))
    return names


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    import boto3

    xray = boto3.client("xray", region_name=REGION)
    start = dt.datetime.now(dt.UTC) - dt.timedelta(minutes=2)
    tid, t = run_case(URL, "C-1001", "How do I download payslips for all employees?")
    print(f"ticket {tid}: route {t.get('route')}, {t.get('agent_status')}")
    found, names = None, []
    for _ in range(12):  # X-Ray indexes within ~1-2 min
        time.sleep(15)
        out = xray.get_trace_summaries(StartTime=start, EndTime=dt.datetime.now(dt.UTC),
                                       FilterExpression=f'annotation.ticket_id = "{tid}"')
        ids = [s["Id"] for s in out.get("TraceSummaries", [])]
        if ids:
            found = ids[0]
            traces = xray.batch_get_traces(TraceIds=ids[:5]).get("Traces", [])
            names = [n for tr in traces for n in node_names(tr)]
            if any((n or "").startswith("node.") for n in names):
                break
    nodes = sorted({n for n in names if (n or "").startswith("node.")})
    ok = bool(found) and len(nodes) >= 5  # the root span shows as the service segment (paynest-worker)
    detail = (f"trace {found}: {len(nodes)} node spans {nodes}" if found
              else "no trace for this ticket in X-Ray after 3 min (stacks updated? collector running?)")
    print(f"{'PASS' if ok else 'FAIL'}  phaseD_trace_per_ticket: {detail}")
    now = dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat()
    with open(ROOT / "results" / "gates.csv", "a", newline="", encoding="utf-8") as fh:
        csv.writer(fh).writerow([now, "D", "trace_per_ticket", REGION, detail[:220], "pass" if ok else "fail", "", ""])
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
