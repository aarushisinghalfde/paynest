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
        raise RuntimeError(f"missing extensions {sorted(missing)}: run python scripts/migrate.py")
    return "extensions " + ", ".join(sorted(REQUIRED_EXTENSIONS))


def check_redis() -> str:
    import redis

    if not settings.REDIS_URL:
        raise RuntimeError("REDIS_URL is not set: add your Upstash URL to .env")
    client = redis.Redis.from_url(settings.REDIS_URL, socket_connect_timeout=3)
    client.ping()
    return f"ping ok ({redis_kind(settings.REDIS_URL)})"


def redis_kind(url: str) -> str:
    """Which cache is in use, without revealing the host or the token (shown on /ready)."""
    from urllib.parse import urlparse

    host = (urlparse(url).hostname or "").lower()
    if host.endswith(".cache.amazonaws.com"):
        return "ElastiCache Valkey"
    if host.endswith(".upstash.io"):
        return "Upstash"
    return "Redis"


def check_queue() -> str:
    return queue_url(sqs_client())


CHECKS = {"postgres": check_postgres, "redis": check_redis, "queue": check_queue}
