#!/usr/bin/env python3
"""Clear the demo's live traffic (laptop side), then the control room starts from fresh tickets.

    python scripts\\reset_demo.py            # snapshot the database, show counts, ask, then delete

1. Takes an RDS snapshot first (paynest-demo-db-before-reset-<time>): the delete cannot be undone otherwise.
2. Shows what would be deleted and kept (agent/demo_reset.py on the server, via SSM; nothing leaves AWS).
3. Deletes only after you type RESET. Keeps the Q3 export, tenants, contracts, rules and the knowledge base.
Then run scripts\\seed_live.py to send fresh questions through the live system.
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.phase4_remote import PREFIX, aws, check_account, stack_output  # noqa: E402

MARK = "RESET_JSON="


def on_server(args: str) -> dict:
    script = f"cd /opt/paynest && docker compose run --rm --no-deps -T worker python -m agent.demo_reset {args}"
    ssm, instance = aws("ssm"), stack_output("ec2", "InstanceId")
    cmd = ssm.send_command(InstanceIds=[instance], DocumentName="AWS-RunShellScript",
                           Parameters={"commands": [script]}, Comment="demo reset")["Command"]["CommandId"]
    for _ in range(60):
        time.sleep(5)
        try:
            inv = ssm.get_command_invocation(CommandId=cmd, InstanceId=instance)
        except ssm.exceptions.InvocationDoesNotExist:
            continue
        if inv["Status"] in ("Pending", "InProgress", "Delayed"):
            continue
        line = next((x for x in reversed(inv.get("StandardOutputContent", "").splitlines()) if x.startswith(MARK)), None)
        if not line:
            sys.exit(f"no result ({inv['Status']}):\n{(inv.get('StandardOutputContent', '') + inv.get('StandardErrorContent', ''))[-800:]}")
        return json.loads(line[len(MARK):])
    sys.exit("timed out")


def main() -> None:
    check_account()
    print("Counting what a reset would delete ...")
    before = on_server("")["before"]
    for k, v in before.items():
        print(f"  {k:22} {v}")
    snap = f"{PREFIX}-db-before-reset-{time.strftime('%Y%m%d-%H%M')}"
    print(f"\nTaking RDS snapshot {snap} (a few minutes) ...")
    rds = aws("rds")
    rds.create_db_snapshot(DBSnapshotIdentifier=snap, DBInstanceIdentifier=f"{PREFIX}-db")
    rds.get_waiter("db_snapshot_available").wait(DBSnapshotIdentifier=snap, WaiterConfig={"Delay": 20, "MaxAttempts": 60})
    print("Snapshot ready. Delete it in the RDS console after a few days if nothing needs restoring.")
    if input(f"\nType RESET to delete {before['live_tickets']} live tickets and what they created: ").strip() != "RESET":
        sys.exit("Nothing deleted.")
    out = on_server("--yes")
    print("Deleted. Now:", json.dumps(out.get("after"), indent=1), f"\nRedis keys cleared: {out.get('redis_keys_deleted')}")
    print("Next: python scripts\\seed_live.py")


if __name__ == "__main__":
    main()
