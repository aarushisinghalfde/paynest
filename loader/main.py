"""Phase 4 loader. Runs ON THE EC2 (the raw data never reaches a laptop or CI):

    docker compose run --rm --no-deps worker python -m loader.main load   --zip-url URL --put-url URL
    docker compose run --rm --no-deps worker python -m loader.main verify --zip-url URL

The zip is fetched through a 15-minute presigned URL made by scripts/run_phase4.py on your
laptop, so the EC2 role itself never gets read access to s3://.../raw/. The labelled set
(masked) is uploaded to s3://.../masked/eval/ through a presigned PUT URL. The last line
printed is PHASE4_JSON=<summary and gates>, read by the laptop script.
"""

import argparse
import io
import json
import sys
import time
import urllib.request
import zipfile

from loader import build as builder
from loader import labelled, verify
from shared import settings
from shared.logs import configure, log_event, safe_error

MARKER = "PHASE4_JSON="


def read_zip(url: str | None = None, path: str | None = None) -> dict[str, str]:
    if url:
        with urllib.request.urlopen(url, timeout=60) as resp:  # noqa: S310 - presigned S3 URL
            data = resp.read()
    else:
        with open(path, "rb") as fh:
            data = fh.read()
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        return {
            n: z.read(n).decode("utf-8")
            for n in z.namelist()
            if n.endswith((".json", ".csv", ".md")) and not n.endswith("/")
        }


def put_json(url: str, payload) -> None:
    body = json.dumps(payload, ensure_ascii=False, indent=1).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="PUT", headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60):  # noqa: S310
        pass


def _connect():
    import psycopg

    return psycopg.connect(settings.DATABASE_URL, connect_timeout=10)


def cmd_load(args) -> dict:
    from intake.vault import from_settings

    if not settings.PII_HMAC_KEY:
        raise RuntimeError("PII_HMAC_KEY is not set")
    raw = read_zip(args.zip_url, args.zip_path)
    t0 = time.time()
    ds = builder.build(
        raw,
        from_settings(settings),
        settings.PII_HMAC_KEY.encode(),
        settings.AWS_REGION,
        int(time.time()),
        routing_table=args.routing,
    )
    with _connect() as conn:
        builder_rows = ds.tables
        from loader import db

        db.write(conn, builder_rows, ds.summary)
    tenants = {t["tenant_id"]: t for t in ds.tables["tenants"]}
    labelled_rows = labelled.export_rows(labelled.stratified(ds.tables["tickets"]), tenants)
    if args.put_url:
        put_json(args.put_url, labelled_rows)
    gates = verify.gates(raw, ds.tables)
    return {
        "command": "load",
        "seconds": round(time.time() - t0, 1),
        "summary": ds.summary,
        "labelled_set": {
            "rows": len(labelled_rows),
            "uploaded": bool(args.put_url),
            "moved": sum(r["moved"] for r in labelled_rows),
            "by_language": _count(labelled_rows, "language"),
            "by_team": _count(labelled_rows, "data_label"),
        },
        "gates": [{"gate": g, "pass": ok, "detail": d} for g, ok, d in gates],
    }


def cmd_verify(args) -> dict:
    from loader import db

    raw = read_zip(args.zip_url, args.zip_path)
    with _connect() as conn:
        tables = db.read_tables(conn)
    gates = verify.gates(raw, tables)
    return {
        "command": "verify",
        "rows": {k: len(v) for k, v in tables.items()},
        "gates": [{"gate": g, "pass": ok, "detail": d} for g, ok, d in gates],
    }


def _count(rows, key):
    out = {}
    for r in rows:
        out[r[key]] = out.get(r[key], 0) + 1
    return dict(sorted(out.items()))


def main(argv=None) -> int:
    configure()
    ap = argparse.ArgumentParser(prog="loader")
    ap.add_argument("command", choices=["load", "verify"])
    ap.add_argument("--zip-url")
    ap.add_argument("--zip-path", help="local zip (development only)")
    ap.add_argument("--put-url", help="presigned PUT URL for the labelled set (load only)")
    ap.add_argument("--routing", default="demo", choices=["demo", "production"])
    args = ap.parse_args(argv)
    if not (args.zip_url or args.zip_path):
        ap.error("--zip-url or --zip-path is required")
    try:
        result = cmd_load(args) if args.command == "load" else cmd_verify(args)
    except Exception as exc:  # noqa: BLE001 - report type and place only, never data
        result = {"command": args.command, "error": safe_error(exc)}
        log_event(__import__("logging").getLogger("loader"), "load_failed", 40, **safe_error(exc))
    print(MARKER + json.dumps(result, default=str, ensure_ascii=False), flush=True)
    return 0 if "error" not in result and all(g["pass"] for g in result.get("gates", [])) else 1


if __name__ == "__main__":
    sys.exit(main())
