#!/usr/bin/env python3
"""Find why `loader load` hit an HTTPError: test the presigned GET and PUT from the EC2.

    $env:AWS_PROFILE = "payce-fde"
    python scripts\\diag_phase4.py

Run scripts\\run_phase4.py first, so the zip is already in raw/. This makes fresh 15-minute
presigned URLs, then on the EC2, inside the worker container (exactly where the loader runs):
  1. GET the raw zip      -> prints the HTTP status and size only, never the content
  2. PUT a tiny test file -> masked/eval/_diag.json, then you can delete it
On failure it prints S3's error XML (an error code and message; no ticket data).
"""

import base64
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.phase4_remote import (  # noqa: E402
    BUCKET,
    RAW_KEY,
    aws,
    check_account,
    s3_presigner,
    stack_output,
)

PROBE = r"""
import sys, urllib.request, urllib.error
def go(name, req):
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            body = r.read()
            print(f"{name}: HTTP {r.status} OK ({len(body)} bytes)")
    except urllib.error.HTTPError as e:
        print(f"{name}: HTTP {e.code} {e.reason}")
        print(e.read()[:600].decode("utf-8", "replace"))
    except Exception as e:
        print(f"{name}: {type(e).__name__}: {e}")
go("GET raw zip", sys.argv[1])
go("PUT test file", urllib.request.Request(sys.argv[2], data=b"{}", method="PUT",
   headers={"Content-Type": "application/json"}))
"""


def main() -> int:
    check_account()
    s3 = s3_presigner()
    get_url = s3.generate_presigned_url(
        "get_object", Params={"Bucket": BUCKET, "Key": RAW_KEY}, ExpiresIn=900
    )
    put_url = s3.generate_presigned_url(
        "put_object",
        Params={"Bucket": BUCKET, "Key": "masked/eval/_diag.json", "ContentType": "application/json"},
        ExpiresIn=900,
    )
    print("presigned URL host:", get_url.split("/")[2])
    print("signing params in GET URL:", sorted(k.split("=")[0] for k in get_url.split("?")[1].split("&")))
    print("signing params in PUT URL:", sorted(k.split("=")[0] for k in put_url.split("?")[1].split("&")))
    b64 = base64.b64encode(PROBE.encode()).decode()
    script = (
        f"echo {b64} | base64 -d > /tmp/paynest_probe.py && cd /opt/paynest && "
        f"docker compose run --rm --no-deps -T -v /tmp/paynest_probe.py:/tmp/probe.py worker "
        f"python /tmp/probe.py '{get_url}' '{put_url}'; rm -f /tmp/paynest_probe.py"
    )
    ssm, instance = aws("ssm"), stack_output("ec2", "InstanceId")
    cid = ssm.send_command(
        InstanceIds=[instance],
        DocumentName="AWS-RunShellScript",
        Parameters={"commands": [script]},
        TimeoutSeconds=300,
        Comment="phase 4 presign diag",
    )["Command"]["CommandId"]
    import time

    for _ in range(60):
        time.sleep(4)
        try:
            inv = ssm.get_command_invocation(CommandId=cid, InstanceId=instance)
        except ssm.exceptions.InvocationDoesNotExist:
            continue
        if inv["Status"] not in ("Pending", "InProgress", "Delayed"):
            print("\n--- on the EC2 ---")
            print(inv.get("StandardOutputContent", "")[-2500:])
            print(inv.get("StandardErrorContent", "")[-1200:])
            return 0
    print("SSM command timed out")
    return 1


if __name__ == "__main__":
    sys.exit(main())
