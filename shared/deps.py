"""Readiness checks for the services every component depends on.

Each check raises on failure and returns a short detail string on success.
"""
from shared import settings
from shared.queue import queue_url, sqs_client

REQUIRED_EXTENSIONS = {"vector", "pg_trgm"}


def check_postgres() -> str:
    import psycopg

    with psycopg.connect(settings.DATABASE_URL, connect_timeout=3) as conn:
        rows = conn.execute("SELECT extname FROM pg_extension").fetchall()
    found = {r[0] for r in rows}
    missing = REQUIRED_EXTENSIONS - found
    if missing:
        raise RuntimeError(f"missing extensions {sorted(missing)}: run alembic upgrade head")
    return "extensions " + ", ".join(sorted(REQUIRED_EXTENSIONS))


def check_valkey() -> str:
    import redis

    client = redis.Redis.from_url(settings.VALKEY_URL, socket_connect_timeout=3)
    client.ping()
    return "ping ok"


def check_queue() -> str:
    return queue_url(sqs_client())


CHECKS = {"postgres": check_postgres, "valkey": check_valkey, "queue": check_queue}
