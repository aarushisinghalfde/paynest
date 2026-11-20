"""Laptop side of phase 4: upload the data room, presign, run the loader on the EC2 via SSM.

The raw files go from your laptop to s3://paynest-demo-data-<account>/raw/ (your own AWS
sign-in). The EC2 gets one 15-minute presigned GET for that zip, and one presigned PUT for
the masked labelled set: its own role still has no access to raw/.
"""

import io
import json
import time
import zipfile
from pathlib import Path

ACCOUNT = "665651551863"
REGION = "ap-southeast-2"
PREFIX = "paynest-demo"
BUCKET = f"{PREFIX}-data-{ACCOUNT}"
RAW_KEY = "raw/data-room/data-room.zip"
LABELLED_KEY = "masked/eval/labelled_set_v1.json"
FOLDERS = ("data/", "integrations/", "process/")  # operational data only (see docs/architecture.md)
MARKER = "PHASE4_JSON="

_session = None


def aws(service: str):
    global _session
    if _session is None:
        import boto3

        _session = boto3.Session(region_name=REGION)
    return _session.client(service)


def check_account() -> str:
    account = aws("sts").get_caller_identity()["Account"]
    if account != ACCOUNT:
        raise SystemExit(f"signed in to {account}, expected {ACCOUNT}")
    return account


def zip_data_room(root: Path) -> tuple[bytes, list[str]]:
    if not (root / "data" / "tickets_export.json").exists():
        raise SystemExit(f"{root} is not the data-room folder (no data/tickets_export.json)")
    buf, names = io.BytesIO(), []
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(root.rglob("*")):
            rel = p.relative_to(root).as_posix()
            if p.is_file() and rel.startswith(FOLDERS) and p.suffix in (".json", ".csv", ".md"):
                z.write(p, "data-room/" + rel)
                names.append(rel)
    return buf.getvalue(), names


def upload_and_presign(data: bytes, want_put: bool) -> tuple[str, str | None]:
    s3 = aws("s3")
    s3.put_object(Bucket=BUCKET, Key=RAW_KEY, Body=data)  # bucket default: SSE-KMS
    get_url = s3.generate_presigned_url(
        "get_object", Params={"Bucket": BUCKET, "Key": RAW_KEY}, ExpiresIn=900
    )
    put_url = None
    if want_put:
        put_url = s3.generate_presigned_url(
            "put_object",
            ExpiresIn=900,
            Params={"Bucket": BUCKET, "Key": LABELLED_KEY, "ContentType": "application/json"},
        )
    return get_url, put_url


def stack_output(stack: str, key: str) -> str:
    outputs = aws("cloudformation").describe_stacks(StackName=f"{PREFIX}-{stack}")["Stacks"][0]["Outputs"]
    return next(o["OutputValue"] for o in outputs if o["OutputKey"] == key)


def run_loader(command: str, get_url: str, put_url: str | None, timeout: int = 900) -> dict:
    args = f"{command} --zip-url '{get_url}'" + (f" --put-url '{put_url}'" if put_url else "")
    script = f"cd /opt/paynest && docker compose run --rm --no-deps -T worker python -m loader.main {args}"
    ssm, instance = aws("ssm"), stack_output("ec2", "InstanceId")
    cmd = ssm.send_command(
        InstanceIds=[instance],
        DocumentName="AWS-RunShellScript",
        Parameters={"commands": [script], "executionTimeout": [str(timeout)]},
        TimeoutSeconds=timeout,
        Comment=f"phase 4 loader {command}",
    )["Command"]["CommandId"]
    print(f"running `loader {command}` on {instance} (SSM command {cmd[:8]}); this takes a few minutes...")
    deadline = time.time() + timeout + 60
    while time.time() < deadline:
        time.sleep(10)
        try:
            inv = ssm.get_command_invocation(CommandId=cmd, InstanceId=instance)
        except ssm.exceptions.InvocationDoesNotExist:
            continue
        if inv["Status"] in ("Pending", "InProgress", "Delayed"):
            continue
        out = inv.get("StandardOutputContent", "")
        line = next((x for x in reversed(out.splitlines()) if x.startswith(MARKER)), None)
        if not line:
            tail = (out + inv.get("StandardErrorContent", ""))[-600:]
            raise SystemExit(f"loader gave no result (status {inv['Status']}). Last output:\n{tail}")
        return json.loads(line[len(MARKER) :])
    raise SystemExit("timed out waiting for the loader")


def download_labelled(dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    aws("s3").download_file(BUCKET, LABELLED_KEY, str(dest))
    return dest
