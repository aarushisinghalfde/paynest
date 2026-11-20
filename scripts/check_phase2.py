#!/usr/bin/env python3
"""Phase 2 gate: the AWS foundation in Sydney is live, private and encrypted.

Run from the repo root, with the stacks deployed and EC2 + RDS running
(`.\\scripts\\demo.ps1 status`):

    $env:AWS_PROFILE = "payce-fde"
    python scripts\\check_phase2.py

Checks, from the laptop (read-only, except one test message on the ticket queue):
  1.  aws_account          signed in to 665651551863
  2.  stacks_complete      network, security, data, iam, rds, ec2, apigw all complete
  3.  public_home          the public HTTPS URL serves the dashboard
  4.  public_api_ready     /api/ready through API Gateway: Postgres, Redis, production queue ok
  5.  worker_in_aws        a test message on paynest-demo-tickets-in is processed by the EC2 worker
  6.  ec2_not_public       the EC2 refuses direct connections; no SSH or open-to-world rules
  7.  rds_private          RDS is not publicly accessible, encrypted, PostgreSQL 17
  8.  encrypted_at_rest    queue and data bucket use the Paynest KMS key
  9.  no_nat_gateway       the VPC has no NAT gateway
  10. images_released      v0.1.0 of app and web are in ECR
  11. secrets_in_ssm       REDIS_URL is stored under /paynest/demo (names only, never values)
Appends one row per check to results/gates.csv. Exit code 0 only if all pass.
"""
import csv
import datetime as dt
import json
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shared import settings  # noqa: E402
from worker.main import PROCESSED_KEY  # noqa: E402

ACCOUNT = "665651551863"
REGION = "ap-southeast-2"
PREFIX = "paynest-demo"
STACKS = ["network", "security", "data", "iam", "rds", "ec2", "apigw"]
RELEASE = "v0.1.0"
HEADER = ["timestamp", "phase", "gate", "region", "value", "result", "commit", "model_ids"]

_session = None


def aws(service: str):
    global _session
    if _session is None:
        import boto3

        _session = boto3.Session(region_name=REGION)
    return _session.client(service)


def stack_output(stack: str, key: str) -> str:
    outputs = aws("cloudformation").describe_stacks(StackName=f"{PREFIX}-{stack}")["Stacks"][0]["Outputs"]
    return next(o["OutputValue"] for o in outputs if o["OutputKey"] == key)


def get(url: str) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")


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
    return f"{len(STACKS)} stacks complete"


def check_public_home():
    url = stack_output("apigw", "Url")
    code, body = get(url + "/")
    assert code == 200 and "Payce Support Assist" in body, f"HTTP {code}"
    return url


def check_public_ready():
    url = stack_output("apigw", "Url")
    code, body = get(url + "/api/ready")
    data = json.loads(body)
    failed = {k: v["detail"] for k, v in data["checks"].items() if not v["ok"]}
    assert code == 200 and not failed, f"HTTP {code}, failing: {failed}"
    queue = data["checks"]["queue"]["detail"]
    assert queue.endswith(f"/{PREFIX}-tickets-in"), f"API uses {queue}, not the production queue"
    return "postgres, redis, production queue ok"


def check_worker_in_aws():
    import redis

    check_id = uuid.uuid4().hex
    sqs = aws("sqs")
    url = sqs.get_queue_url(QueueName=f"{PREFIX}-tickets-in")["QueueUrl"]
    sqs.send_message(QueueUrl=url, MessageBody=json.dumps({"check_id": check_id}))
    cache = redis.Redis.from_url(settings.REDIS_URL)   # the same Upstash database the EC2 uses
    deadline = time.time() + 60
    while time.time() < deadline:
        if cache.get(PROCESSED_KEY.format(check_id)):
            return f"message {check_id[:8]} processed on the EC2"
        time.sleep(2)
    raise AssertionError("the EC2 worker did not process the test message within 60 s")


def check_ec2_not_public():
    ip = stack_output("ec2", "ElasticIp")
    try:
        socket.create_connection((ip, 80), timeout=5).close()
        raise AssertionError(f"port 80 on {ip} accepted a direct connection")
    except OSError:
        pass  # refused or timed out: what we want
    exports = {e["Name"]: e["Value"] for e in aws("cloudformation").list_exports()["Exports"]}
    group_id = exports[f"{PREFIX}-Ec2SecurityGroupId"]
    group = aws("ec2").describe_security_groups(GroupIds=[group_id])["SecurityGroups"][0]
    for rule in group["IpPermissions"]:
        assert rule.get("FromPort") != 22, "SSH port 22 is open"
        assert not any(r.get("CidrIp") == "0.0.0.0/0" for r in rule.get("IpRanges", [])), \
            "a rule is open to 0.0.0.0/0"
    return f"{ip}:80 refuses direct traffic; no SSH; no 0.0.0.0/0"


def check_rds_private():
    db = aws("rds").describe_db_instances(DBInstanceIdentifier=f"{PREFIX}-db")["DBInstances"][0]
    assert not db["PubliclyAccessible"], "RDS is publicly accessible"
    assert db["StorageEncrypted"], "RDS storage is not encrypted"
    assert db["EngineVersion"].startswith("17."), f"engine {db['EngineVersion']}"
    return f"private, encrypted, PostgreSQL {db['EngineVersion']}, {db['DBInstanceStatus']}"


def check_encryption():
    sqs = aws("sqs")
    url = sqs.get_queue_url(QueueName=f"{PREFIX}-tickets-in")["QueueUrl"]
    attrs = sqs.get_queue_attributes(QueueUrl=url, AttributeNames=["KmsMasterKeyId"])["Attributes"]
    assert attrs.get("KmsMasterKeyId"), "queue is not KMS-encrypted"
    bucket = f"{PREFIX}-data-{ACCOUNT}"
    rules = aws("s3").get_bucket_encryption(Bucket=bucket)["ServerSideEncryptionConfiguration"]["Rules"]
    algo = rules[0]["ApplyServerSideEncryptionByDefault"]["SSEAlgorithm"]
    assert algo == "aws:kms", f"bucket uses {algo}"
    return "queue KMS, bucket aws:kms"


def check_no_nat():
    exports = {e["Name"]: e["Value"] for e in aws("cloudformation").list_exports()["Exports"]}
    vpc = exports[f"{PREFIX}-VpcId"]
    nats = aws("ec2").describe_nat_gateways(
        Filters=[{"Name": "vpc-id", "Values": [vpc]}, {"Name": "state", "Values": ["pending", "available"]}]
    )["NatGateways"]
    assert not nats, f"{len(nats)} NAT gateway(s) in {vpc}"
    return f"none in {vpc}"


def check_images():
    ecr = aws("ecr")
    for repo in ("app", "web"):
        ecr.describe_images(repositoryName=f"{PREFIX}/{repo}", imageIds=[{"imageTag": RELEASE}])
    return f"app and web {RELEASE}"


def check_secrets():
    names = [p["Name"] for p in aws("ssm").get_parameters_by_path(Path="/paynest/demo")["Parameters"]]
    assert "/paynest/demo/REDIS_URL" in names, f"found {names}"
    return ", ".join(n.rsplit("/", 1)[1] for n in names)


CHECKS = [
    ("aws_account", check_account),
    ("stacks_complete", check_stacks),
    ("public_home", check_public_home),
    ("public_api_ready", check_public_ready),
    ("worker_in_aws", check_worker_in_aws),
    ("ec2_not_public", check_ec2_not_public),
    ("rds_private", check_rds_private),
    ("encrypted_at_rest", check_encryption),
    ("no_nat_gateway", check_no_nat),
    ("images_released", check_images),
    ("secrets_in_ssm", check_secrets),
]


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
        try:
            detail = fn()
            print(f"PASS  {name}: {detail}")
            rows.append([now, 2, name, REGION, detail, "pass", commit, ""])
        except Exception as exc:  # noqa: BLE001
            all_ok = False
            print(f"FAIL  {name}: {exc}")
            rows.append([now, 2, name, REGION, str(exc)[:200], "fail", commit, ""])
            if name == "aws_account":
                break                       # nothing else is meaningful in the wrong account

    settings.RESULTS_DIR.mkdir(exist_ok=True)
    path = settings.RESULTS_DIR / "gates.csv"
    new = not path.exists()
    with open(path, "a", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        if new:
            writer.writerow(HEADER)
        writer.writerows(rows)
    print(f"\nPHASE 2 GATE: {'PASS' if all_ok else 'FAIL'} (results/gates.csv)")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
