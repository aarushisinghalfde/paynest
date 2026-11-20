#!/usr/bin/env python3
"""Phase 3 gate: the PII gate and vault work end to end in AWS.

Run from the repo root after the vault, observability and ec2 stacks are applied and the
v0.2.0 images are running (`.\\scripts\\demo.ps1 status`):

    $env:AWS_PROFILE = "payce-fde"
    python scripts\\check_phase3.py

Checks (two synthetic tickets from tests/fixtures/pii_seeded.json are submitted; values
are never printed, only kinds and counts):
  1.  aws_account            signed in to 665651551863
  2.  stacks_complete        vault and observability complete
  3.  leak_seeded_local      0 raw values survive on the 60 + 12 seeded tickets (this laptop)
  4.  public_ticket_masked   POST /api/tickets -> masked within 90 s, no raw value in masked_body
  5.  presidio_layer_on      the EC2 worker masked with Presidio + spaCy (not rules only)
  6.  inbox_deleted          the raw inbox row is gone from Postgres (checked on the EC2)
  7.  reveal_right_ticket    vault-reveal returns the original value for the right ticket
  8.  reveal_wrong_ticket    vault-reveal returns nothing for another ticket or an unknown one
  9.  ec2_cannot_read_vault  on the EC2, dynamodb:GetItem and kms:Decrypt are denied
  10. admin_cannot_decrypt   your own admin role cannot kms:Decrypt the vault ciphertext either
  11. logs_have_no_values    CloudWatch has the ticket_masked event and none of the raw values
  12. alarms_exist           the 4 alarms exist; pii-blocked is not in ALARM
Appends one row per check to results/gates.csv. Exit code 0 only if all pass.
"""
import base64
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
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pii import mask_ticket  # noqa: E402
from pii.normalize import normalize_digits  # noqa: E402
from shared import settings  # noqa: E402

ACCOUNT = "665651551863"
REGION = "ap-southeast-2"
PREFIX = "paynest-demo"
STACKS = ["vault", "observability"]
TENANT = "check-phase3"
ALARMS = ["pii-blocked", "pii-ner-off", "worker-failures", "tickets-dlq-not-empty"]
HEADER = ["timestamp", "phase", "gate", "region", "value", "result", "commit", "model_ids"]
FIXTURES = settings.ROOT / "tests" / "fixtures"
TOKEN_RE = re.compile(r"<[A-Z_]+_\d+>")

_session = None
state: dict = {}          # shared between checks: submitted tickets, tokens, ciphertext


def aws(service: str):
    global _session
    if _session is None:
        import boto3

        _session = boto3.Session(region_name=REGION)
    return _session.client(service)


def stack_output(stack: str, key: str) -> str:
    outputs = aws("cloudformation").describe_stacks(StackName=f"{PREFIX}-{stack}")["Stacks"][0]["Outputs"]
    return next(o["OutputValue"] for o in outputs if o["OutputKey"] == key)


def http(method: str, url: str, body: dict | None = None) -> tuple[int, dict]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as exc:
        return exc.code, {}


def leaked(value: str, text: str) -> bool:
    v, t = normalize_digits(value), normalize_digits(text)
    sq = re.sub(r"[\s\-]", "", v)
    return v in t or (sq.isascii() and sq.isalnum() and len(sq) >= 6 and sq in re.sub(r"[\s\-]", "", t))


def run_on_ec2(script: str, timeout: int = 90) -> str:
    """Run a shell script on the Paynest EC2 through SSM Run Command (no SSH); return stdout."""
    ssm = aws("ssm")
    instance = stack_output("ec2", "InstanceId")
    cmd = ssm.send_command(InstanceIds=[instance], DocumentName="AWS-RunShellScript",
                           Parameters={"commands": [script]}, TimeoutSeconds=timeout)["Command"]["CommandId"]
    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(3)
        try:
            inv = ssm.get_command_invocation(CommandId=cmd, InstanceId=instance)
        except ssm.exceptions.InvocationDoesNotExist:
            continue
        if inv["Status"] not in ("Pending", "InProgress", "Delayed"):
            return inv.get("StandardOutputContent", "") + inv.get("StandardErrorContent", "")
    raise AssertionError("SSM command on the EC2 timed out")


def invoke_reveal(ticket_id: str, token: str) -> dict:
    resp = aws("lambda").invoke(
        FunctionName=f"{PREFIX}-vault-reveal",
        Payload=json.dumps({"ticket_id": ticket_id, "token": token, "requested_by": "check_phase3",
                            "reason": "phase 3 gate check"}).encode())
    return json.loads(resp["Payload"].read())


# ---------------------------------------------------------------- checks
def check_account():
    account = aws("sts").get_caller_identity()["Account"]
    assert account == ACCOUNT, f"signed in to {account}, expected {ACCOUNT}"
    return account


def check_stacks():
    cf = aws("cloudformation")
    bad = {}
    for name in STACKS:
        try:
            status = cf.describe_stacks(StackName=f"{PREFIX}-{name}")["Stacks"][0]["StackStatus"]
        except Exception as exc:  # noqa: BLE001
            status = f"missing ({type(exc).__name__})"
        if status not in ("CREATE_COMPLETE", "UPDATE_COMPLETE"):
            bad[name] = status
    assert not bad, f"not complete: {bad}"
    return f"{', '.join(STACKS)} complete"


def check_leak_local():
    tickets = [t for f in ("pii_seeded.json", "pii_seeded_ner.json")
               for t in json.loads((FIXTURES / f).read_text(encoding="utf-8"))]
    bad = []
    for t in tickets:
        masked = mask_ticket(t["body"], sender_name=t["sender_name"]).text
        if any(leaked(v, masked) for v in t["raw_values"]):
            bad.append(t["id"])
    assert not bad, f"leaks in {bad}"
    return f"0 raw values in {len(tickets)} seeded tickets"


def check_public_ticket():
    seed = {t["id"]: t for t in json.loads((FIXTURES / "pii_seeded.json").read_text(encoding="utf-8"))}
    url = stack_output("apigw", "Url") + "/api/tickets"
    state["start_ms"] = int(time.time() * 1000) - 5000
    submitted = []
    for sid in ("SEED-001", "SEED-002"):
        t = seed[sid]
        payload = {"tenant_id": TENANT, "body": t["body"], "sender_name": t["sender_name"],
                   "sender_email": t["sender_email"], "sender_phone": t["sender_phone"]}
        code, body = http("POST", url, payload)
        assert code == 202, f"POST /api/tickets returned HTTP {code}"
        submitted.append({"id": body["ticket_id"], "seed": t})
    deadline = time.time() + 90
    pending = list(submitted)
    while pending and time.time() < deadline:
        time.sleep(3)
        for t in list(pending):
            code, got = http("GET", f"{url}/{t['id']}")
            if code == 200 and got["status"] != "received":
                t["row"] = got
                pending.remove(t)
    assert not pending, f"{len(pending)} ticket(s) still not masked after 90 s (worker down?)"
    for t in submitted:
        row = t["row"]
        assert row["status"] == "masked", f"status {row['status']}, reasons {row['pii_block_reasons']}"
        kinds = [k for k in t["seed"]["raw_values"] if leaked(k, t["row"]["masked_body"])]
        assert not kinds, f"{len(kinds)} raw value(s) visible in masked_body"
    state["tickets"] = submitted          # later checks run only once both tickets are masked
    counts = submitted[0]["row"]["pii_counts"]
    return f"2 tickets masked; first: {counts}"


def check_presidio():
    layers = {t["row"]["ner_layer"] for t in state["tickets"]}
    assert layers == {"presidio"}, f"ner_layer {layers}"
    return "presidio"


def check_inbox_deleted():
    ids = [t["id"] for t in state["tickets"]]
    script = "\n".join([
        "cat > /tmp/inbox_check.py <<'PY'",
        "import os, psycopg",
        "with psycopg.connect(os.environ['DATABASE_URL']) as c:",
        "    n = c.execute('SELECT count(*) FROM ticket_inbox WHERE ticket_id = ANY(%s::uuid[])',",
        f"                  ({ids!r},)).fetchone()[0]",
        "print('INBOX_ROWS=%s' % n)",
        "PY",
        "cd /opt/paynest && docker compose exec -T api python - < /tmp/inbox_check.py",
        "rm -f /tmp/inbox_check.py",
    ])
    out = run_on_ec2(script)
    m = re.search(r"INBOX_ROWS=(\d+)", out)
    assert m, f"could not read the inbox on the EC2: {out[-200:]}"
    assert m.group(1) == "0", f"{m.group(1)} raw inbox row(s) left"
    return "0 raw inbox rows for the 2 tickets"


def check_reveal_right():
    t = state["tickets"][0]
    checked = 0
    for token in sorted(set(TOKEN_RE.findall(t["row"]["masked_body"]))):
        out = invoke_reveal(t["id"], token)
        assert out.get("status") == "ok", f"{token}: {out.get('status')}"
        assert any(normalize_digits(out["value"]) == normalize_digits(v) for v in t["seed"]["raw_values"]), \
            f"{token}: revealed value is not one of the ticket's raw values"
        checked += 1
    sender = invoke_reveal(t["id"], "<SENDER_EMAIL>")
    assert sender.get("status") == "ok" and sender["value"] == t["seed"]["sender_email"], "sender email"
    state["token"] = sorted(set(TOKEN_RE.findall(t["row"]["masked_body"])))[0]
    return f"{checked} tokens + sender email revealed for the right ticket"


def check_reveal_wrong():
    first, second = state["tickets"]
    token = state["token"]
    unknown = invoke_reveal(str(uuid.uuid4()), token)
    assert unknown.get("status") == "not_found", f"unknown ticket: {unknown.get('status')}"
    right = invoke_reveal(first["id"], token)["value"]
    other = invoke_reveal(second["id"], token)
    assert other.get("status") != "ok" or other["value"] != right, \
        "another ticket revealed this ticket's value"
    return f"unknown ticket not_found; other ticket gives {other.get('status')}, never this ticket's value"


def _ciphertext() -> tuple[dict, str]:
    t = state["tickets"][0]
    item = aws("dynamodb").get_item(TableName=stack_output("vault", "VaultTableName"),
                                    Key={"ticket_id": {"S": t["id"]}, "token": {"S": state["token"]}})["Item"]
    ctx = {"ticket_id": t["id"], "token": state["token"], "tenant_id": item["tenant_id"]["S"]}
    return ctx, base64.b64encode(item["ciphertext"]["B"]).decode()


def check_ec2_cannot_read():
    ctx, blob = _ciphertext()
    table = stack_output("vault", "VaultTableName")
    key = json.dumps({"ticket_id": {"S": ctx["ticket_id"]}, "token": {"S": ctx["token"]}})
    script = "\n".join([
        "set +e",
        f"aws dynamodb get-item --region {REGION} --table-name {table} --key '{key}' >/dev/null 2>/tmp/g.err;"
        " echo GET_EXIT=$?; grep -o AccessDenied /tmp/g.err | head -1",
        f"echo '{blob}' | base64 -d > /tmp/ct.bin",
        f"aws kms decrypt --region {REGION} --ciphertext-blob fileb:///tmp/ct.bin"
        f" --encryption-context '{json.dumps(ctx)}' >/dev/null 2>/tmp/d.err;"
        " echo DECRYPT_EXIT=$?; grep -o AccessDenied /tmp/d.err | head -1",
        "rm -f /tmp/ct.bin /tmp/g.err /tmp/d.err",
    ])
    out = run_on_ec2(script)
    assert "GET_EXIT=0" not in out, "the EC2 role could read a vault item"
    assert "DECRYPT_EXIT=0" not in out, "the EC2 role could decrypt a vault value"
    assert out.count("AccessDenied") >= 2, f"expected two AccessDenied errors: {out[-300:]}"
    return "GetItem and Decrypt both AccessDenied on the EC2"


def check_admin_cannot_decrypt():
    ctx, blob = _ciphertext()
    kms = aws("kms")
    try:
        kms.decrypt(CiphertextBlob=base64.b64decode(blob), EncryptionContext=ctx)
    except kms.exceptions.ClientError as exc:
        code = exc.response["Error"]["Code"]
        assert code == "AccessDeniedException", f"unexpected {code}"
        return "AccessDenied for your admin role (only vault-reveal can decrypt)"
    raise AssertionError("your admin role decrypted a vault value directly")


def check_logs():
    logs = aws("logs")
    group = stack_output("observability", "AppLogGroupName")
    t = state["tickets"][0]
    deadline, found = time.time() + 60, False
    while time.time() < deadline and not found:
        events = logs.filter_log_events(
            logGroupName=group, startTime=state["start_ms"],
            filterPattern=f'{{ $.event = "ticket_masked" && $.ticket_id = "{t["id"]}" }}')["events"]
        found = bool(events)
        if not found:
            time.sleep(5)
    assert found, "no ticket_masked event in CloudWatch for the test ticket"
    hits = 0
    for value in {v for tk in state["tickets"] for v in tk["seed"]["raw_values"] if len(v) >= 4}:
        pattern = '"' + value.replace('"', "") + '"'
        hits += len(logs.filter_log_events(logGroupName=group, startTime=state["start_ms"],
                                           filterPattern=pattern, limit=5)["events"])
    assert hits == 0, f"{hits} log event(s) contain a raw value"
    return "ticket_masked logged; 0 events contain raw values"


def check_alarms():
    names = [f"{PREFIX}-{a}" for a in ALARMS]
    found = {a["AlarmName"]: a["StateValue"]
             for a in aws("cloudwatch").describe_alarms(AlarmNames=names)["MetricAlarms"]}
    missing = set(names) - set(found)
    assert not missing, f"missing {sorted(missing)}"
    assert found[f"{PREFIX}-pii-blocked"] != "ALARM", "pii-blocked is in ALARM: a ticket was quarantined"
    return ", ".join(f"{k.removeprefix(PREFIX + '-')}={v}" for k, v in found.items())


CHECKS = [
    ("aws_account", check_account),
    ("stacks_complete", check_stacks),
    ("leak_seeded_local", check_leak_local),
    ("public_ticket_masked", check_public_ticket),
    ("presidio_layer_on", check_presidio),
    ("inbox_deleted", check_inbox_deleted),
    ("reveal_right_ticket", check_reveal_right),
    ("reveal_wrong_ticket", check_reveal_wrong),
    ("ec2_cannot_read_vault", check_ec2_cannot_read),
    ("admin_cannot_decrypt", check_admin_cannot_decrypt),
    ("logs_have_no_values", check_logs),
    ("alarms_exist", check_alarms),
]
NEEDS_TICKETS = {"presidio_layer_on", "inbox_deleted", "reveal_right_ticket", "reveal_wrong_ticket",
                 "ec2_cannot_read_vault", "admin_cannot_decrypt", "logs_have_no_values"}


def git_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True,
                                       stderr=subprocess.DEVNULL).strip()
    except Exception:  # noqa: BLE001
        return ""


def main() -> int:
    now = dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat()
    commit = git_commit()
    rows, all_ok = [], True
    for name, fn in CHECKS:
        if name in NEEDS_TICKETS and not state.get("tickets") or \
                name in ("reveal_wrong_ticket", "ec2_cannot_read_vault", "admin_cannot_decrypt") \
                and not state.get("token"):
            detail, ok = "skipped: an earlier check failed", False
        else:
            try:
                detail, ok = fn(), True
            except Exception as exc:  # noqa: BLE001 - messages above never include values
                detail, ok = f"{type(exc).__name__}: {exc}"[:200], False
        all_ok &= ok
        print(f"{'PASS' if ok else 'FAIL'}  {name}: {detail}")
        rows.append([now, 3, name, REGION, detail, "pass" if ok else "fail", commit, ""])
        if name == "aws_account" and not ok:
            break                       # nothing else is meaningful in the wrong account

    path = settings.RESULTS_DIR / "gates.csv"
    new = not path.exists()
    with open(path, "a", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        if new:
            writer.writerow(HEADER)
        writer.writerows(rows)
    print(f"\nPHASE 3 GATE: {'PASS' if all_ok else 'FAIL'} (results/gates.csv)")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
