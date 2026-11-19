#!/usr/bin/env python3
"""Phase 1 gate. Run after `docker compose up -d --build --wait`:

    python scripts/check_phase1.py

Checks, from the laptop:
  1. API /health returns 200
  2. API /ready: Postgres (with vector + pg_trgm), Redis and the queue are reachable
  3. Web: /chat and /review load
  4. Mock payroll API /health returns 200
  5. Worker: a test message sent to tickets-in is received and processed
  6. Migrations: both extensions exist in Postgres (scripts/migrate.py ran)
Appends one row per check to results/gates.csv. Exit code 0 only if all pass.
"""
import csv
import datetime as dt
import json
import subprocess
import sys
import time
import urllib.request
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shared import settings  # noqa: E402
from shared.deps import check_postgres  # noqa: E402
from shared.queue import queue_url, sqs_client  # noqa: E402
from worker.main import PROCESSED_KEY  # noqa: E402

HEADER = ["timestamp", "phase", "gate", "region", "value", "result", "commit", "model_ids"]
API = "http://localhost:8000"
WEB = "http://localhost:3000"
MOCK = "http://localhost:8081"


def get(url: str) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")


def check_health():
    code, body = get(f"{API}/health")
    assert code == 200, f"HTTP {code}"
    return json.loads(body)["aws_region"]


def check_ready():
    code, body = get(f"{API}/ready")
    data = json.loads(body)
    failed = {k: v["detail"] for k, v in data["checks"].items() if not v["ok"]}
    assert code == 200 and not failed, f"HTTP {code}, failing: {failed}"
    return ", ".join(data["checks"])


def check_web():
    out = []
    for page in ("/chat", "/review"):
        code, body = get(f"{WEB}{page}")
        assert code == 200 and 'id="root"' in body, f"{page}: HTTP {code}"
        out.append(page)
    return " and ".join(out) + " load"


def check_mock():
    code, _ = get(f"{MOCK}/health")
    assert code == 200, f"HTTP {code}"
    return "health 200"


def check_worker():
    import redis

    check_id = uuid.uuid4().hex
    client = sqs_client()
    client.send_message(QueueUrl=queue_url(client), MessageBody=json.dumps({"check_id": check_id}))
    cache = redis.Redis.from_url(settings.REDIS_URL)
    deadline = time.time() + 30
    while time.time() < deadline:
        if cache.get(PROCESSED_KEY.format(check_id)):
            return f"message {check_id[:8]} processed"
        time.sleep(1)
    raise AssertionError("worker did not process the test message within 30 s "
                         "(see: docker compose logs worker)")


def git_commit() -> str:
    try:
        out = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True,
                                      stderr=subprocess.DEVNULL)
        return out.strip()
    except Exception:  # noqa: BLE001
        return ""


CHECKS = [
    ("api_health", check_health),
    ("api_ready", check_ready),
    ("web_pages", check_web),
    ("mock_payroll_health", check_mock),
    ("worker_receives_message", check_worker),
    ("migrations_extensions", check_postgres),
]


def main() -> int:
    now = dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat()
    commit = git_commit()
    rows, all_ok = [], True
    for name, fn in CHECKS:
        try:
            detail = fn()
            print(f"PASS  {name}: {detail}")
            rows.append([now, 1, name, "local", detail, "pass", commit, ""])
        except Exception as exc:  # noqa: BLE001
            all_ok = False
            print(f"FAIL  {name}: {exc}")
            rows.append([now, 1, name, "local", str(exc)[:200], "fail", commit, ""])

    settings.RESULTS_DIR.mkdir(exist_ok=True)
    path = settings.RESULTS_DIR / "gates.csv"
    new = not path.exists()
    with open(path, "a", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        if new:
            writer.writerow(HEADER)
        writer.writerows(rows)
    print(f"\nPHASE 1 GATE: {'PASS' if all_ok else 'FAIL'} (results/gates.csv)")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
