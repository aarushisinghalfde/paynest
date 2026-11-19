#!/usr/bin/env python3
"""Apply db/migrations/*.sql in name order, each exactly once.

    python scripts/migrate.py

Applied files are recorded in the schema_migrations table. A Postgres advisory lock
stops two processes (for example two API containers) migrating at the same time.
Each file runs in its own transaction: if one fails, it is rolled back and nothing
after it runs.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shared import settings  # noqa: E402

MIGRATIONS_DIR = settings.ROOT / "db" / "migrations"
LOCK_ID = 727274  # any constant; shared by every process running migrations


def pending(files: list[Path], applied: set[str]) -> list[Path]:
    """Files not yet applied, in name order."""
    return sorted((f for f in files if f.name not in applied), key=lambda f: f.name)


def main() -> int:
    import psycopg

    files = list(MIGRATIONS_DIR.glob("*.sql"))
    with psycopg.connect(settings.DATABASE_URL, autocommit=True) as conn:
        conn.execute("SELECT pg_advisory_lock(%s)", (LOCK_ID,))
        try:
            conn.execute("""CREATE TABLE IF NOT EXISTS schema_migrations (
                                version    text PRIMARY KEY,
                                applied_at timestamptz NOT NULL DEFAULT now())""")
            applied = {r[0] for r in conn.execute("SELECT version FROM schema_migrations")}
            todo = pending(files, applied)
            for path in todo:
                with conn.transaction():
                    conn.execute(path.read_text(encoding="utf-8"))
                    conn.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (path.name,))
                print(f"applied {path.name}")
            print(f"migrations up to date ({len(applied) + len(todo)} applied)")
        finally:
            conn.execute("SELECT pg_advisory_unlock(%s)", (LOCK_ID,))
    return 0


if __name__ == "__main__":
    sys.exit(main())
