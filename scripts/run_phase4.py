#!/usr/bin/env python3
"""Phase 4: load the data room into the Sydney database, masked, from your laptop.

    git clone https://github.com/niti007/paynest-support-discovery ..\\paynest-support-discovery
    $env:AWS_PROFILE = "payce-fde"
    python scripts\\run_phase4.py --data-room ..\\paynest-support-discovery\\data-room

What happens:
  1. zips data/, integrations/ and process/ (operational data only) and uploads the zip to
     s3://paynest-demo-data-665651551863/raw/ with your sign-in;
  2. makes a 15-minute presigned GET for the zip and a presigned PUT for the labelled set;
  3. runs `loader load` on the EC2 through SSM Run Command: parse, mask (PII gate), vault the
     raw values, write every table in one transaction, build the 200-ticket labelled set;
  4. prints the summary and the gate results, and downloads the masked labelled set to
     evals/local/ (git-ignored: masked client data does not go into the public repo).
Then run `python scripts\\check_phase4.py` to verify from the database and record the gate.
Re-running is safe (upserts by deterministic ids; the vault is append-only).
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts import phase4_remote as remote  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--data-room", type=Path, default=ROOT.parent / "paynest-support-discovery" / "data-room")
    args = ap.parse_args()
    remote.check_account()
    data, names = remote.zip_data_room(args.data_room.resolve())
    print(f"zipped {len(names)} files ({len(data) // 1024} KB) from {args.data_room}")
    get_url, put_url = remote.upload_and_presign(data, want_put=True)
    print(f"uploaded to s3://{remote.BUCKET}/{remote.RAW_KEY}")
    result = remote.run_loader("load", get_url, put_url)
    if "error" in result:
        print(f"LOAD FAILED: {result['error']}")
        return 1
    print(json.dumps(result["summary"], indent=1))
    print(f"labelled set: {json.dumps(result['labelled_set'])}")
    for g in result["gates"]:
        print(f"{'PASS' if g['pass'] else 'FAIL'}  {g['gate']}: {g['detail']}")
    path = remote.download_labelled(ROOT / "evals" / "local" / "labelled_set_v1.json")
    print(f"masked labelled set saved to {path.relative_to(ROOT)} (git-ignored)")
    return 0 if all(g["pass"] for g in result["gates"]) else 1


if __name__ == "__main__":
    sys.exit(main())
