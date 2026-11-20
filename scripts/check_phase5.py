#!/usr/bin/env python3
"""Phase 5 gate: one ticket end to end through the real graph in AWS.

    $env:AWS_PROFILE = "payce-fde"
    python scripts\\check_phase5.py

  1. chat_to_reply        POST /api/tickets -> the graph replies within 90 s (agent_status replied)
  2. idempotent_post      20 parallel posts with one Idempotency-Key -> 1 ticket
  3. checkpoints_saved    LangGraph checkpoint rows exist for the ticket's thread (on the EC2)
  4. poison_to_dlq        a message that always fails reaches the dead-letter queue (about 4 min)
The crash-and-resume test runs in CI (tests/test_agent_graph.py) because killing the live
worker on purpose is not a safe check. Appends rows to results/gates.csv.
"""

import csv
import datetime as dt
import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.phase4_remote import REGION, aws, check_account, stack_output  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
state: dict = {}


def http(method, url, body=None, headers=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url, data=data, method=method, headers={"Content-Type": "application/json", **(headers or {})}
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as exc:
        return exc.code, {}


def run_on_ec2(script: str, timeout=120) -> str:
    ssm, instance = aws("ssm"), stack_output("ec2", "InstanceId")
    cid = ssm.send_command(
        InstanceIds=[instance],
        DocumentName="AWS-RunShellScript",
        Parameters={"commands": [script]},
        TimeoutSeconds=timeout,
    )["Command"]["CommandId"]
    for _ in range(timeout // 3):
        time.sleep(3)
        try:
            inv = ssm.get_command_invocation(CommandId=cid, InstanceId=instance)
        except ssm.exceptions.InvocationDoesNotExist:
            continue
        if inv["Status"] not in ("Pending", "InProgress", "Delayed"):
            return inv.get("StandardOutputContent", "") + inv.get("StandardErrorContent", "")
    raise AssertionError("SSM command timed out")


def check_chat_to_reply():
    url = stack_output("apigw", "Url") + "/api/tickets"
    code, body = http(
        "POST",
        url,
        {"tenant_id": "C-1001", "body": "How do I add a new employee?", "channel": "chat"},
        {"Idempotency-Key": uuid.uuid4().hex},
    )
    assert code == 202, f"POST returned {code}"
    tid = state["ticket"] = body["ticket_id"]
    for _ in range(30):
        time.sleep(3)
        _, t = http("GET", f"{url}/{tid}")
        if t.get("agent_status") == "replied" and t.get("replies"):
            return f"replied in the chat ({t['route']}, team {t['team']})"
    raise AssertionError(f"no reply after 90 s (status {t.get('agent_status')})")


def check_idempotent():
    url, key = stack_output("apigw", "Url") + "/api/tickets", uuid.uuid4().hex
    payload = {"tenant_id": "C-1001", "body": "Same message posted twenty times", "channel": "chat"}
    with ThreadPoolExecutor(20) as pool:
        results = list(pool.map(lambda _: http("POST", url, payload, {"Idempotency-Key": key}), range(20)))
    ids = {b.get("ticket_id") for _, b in results}
    assert len(ids) == 1 and None not in ids, f"{len(ids)} tickets"
    created = sum(c == 202 for c, _ in results)
    return f"20 posts -> 1 ticket ({created} created, {20 - created} repeats)"


def check_checkpoints():
    tid = state["ticket"]
    script = "\n".join(
        [
            "cat > /tmp/cp_check.py <<'PY'",
            "import os, psycopg",
            "with psycopg.connect(os.environ['DATABASE_URL']) as c:",
            "    q = 'SELECT count(*) FROM checkpoints WHERE thread_id = %s'",
            f"    n = c.execute(q, ('{tid}',)).fetchone()[0]",
            "print('CP=%s' % n)",
            "PY",
            "cd /opt/paynest && docker compose exec -T api python - < /tmp/cp_check.py",
            "rm -f /tmp/cp_check.py",
        ]
    )
    out = run_on_ec2(script)
    m = re.search(r"CP=(\d+)", out)
    assert m and int(m.group(1)) > 0, f"no checkpoints found: {out[-200:]}"
    return f"{m.group(1)} checkpoint rows for thread {tid[:8]}"


def check_poison():
    sqs = aws("sqs")
    url = sqs.get_queue_url(QueueName="paynest-demo-tickets-in")["QueueUrl"]
    dlq = sqs.get_queue_url(QueueName="paynest-demo-tickets-dlq")["QueueUrl"]
    marker = uuid.uuid4().hex
    sqs.send_message(QueueUrl=url, MessageBody=json.dumps({"ticket_id": str(uuid.uuid4()), "poison": marker}))
    deadline = time.time() + 330  # 3 tries x 60 s visibility, plus margin
    while time.time() < deadline:
        msgs = sqs.receive_message(
            QueueUrl=dlq, MaxNumberOfMessages=10, WaitTimeSeconds=10, VisibilityTimeout=5
        ).get("Messages", [])
        for msg in msgs:
            if marker in msg["Body"]:
                sqs.delete_message(QueueUrl=dlq, ReceiptHandle=msg["ReceiptHandle"])
                return "unknown ticket id failed 3 times and moved to tickets-dlq"
    raise AssertionError("poison message not in the DLQ after 5.5 min")


CHECKS = [
    ("chat_to_reply", check_chat_to_reply),
    ("idempotent_post", check_idempotent),
    ("checkpoints_saved", check_checkpoints),
    ("poison_to_dlq", check_poison),
]


def main() -> int:
    check_account()
    now = dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat()
    try:
        commit = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True).strip()
    except Exception:  # noqa: BLE001
        commit = ""
    rows, ok_all = [], True
    for name, fn in CHECKS:
        if name == "checkpoints_saved" and "ticket" not in state:
            detail, ok = "skipped: chat_to_reply failed", False
        else:
            try:
                detail, ok = fn(), True
            except Exception as exc:  # noqa: BLE001
                detail, ok = f"{type(exc).__name__}: {exc}"[:200], False
        ok_all &= ok
        print(f"{'PASS' if ok else 'FAIL'}  {name}: {detail}")
        rows.append([now, 5, name, REGION, detail, "pass" if ok else "fail", commit, ""])
    with open(ROOT / "results" / "gates.csv", "a", newline="", encoding="utf-8") as fh:
        csv.writer(fh).writerows(rows)
    print(f"\nPHASE 5 GATE: {'PASS' if ok_all else 'FAIL'} (results/gates.csv)")
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
