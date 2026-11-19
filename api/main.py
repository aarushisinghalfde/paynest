"""Payce Support Assist API.

Phase 1: liveness (/health) and readiness (/ready). Ticket intake, chat and review
WebSockets arrive in phases 5 and 10.
"""
from fastapi import FastAPI, Response

from shared import deps, settings

app = FastAPI(title="Payce Support Assist API", version="0.1.0")


@app.get("/health")
def health() -> dict:
    """Liveness: the process is up. Never touches other services."""
    return {"status": "ok", "region": settings.REGION, "aws_region": settings.AWS_REGION}


@app.get("/ready")
def ready(response: Response) -> dict:
    """Readiness: Postgres (with extensions), Valkey and the queue are reachable."""
    checks = {}
    for name, check in deps.CHECKS.items():
        try:
            checks[name] = {"ok": True, "detail": check()}
        except Exception as exc:  # noqa: BLE001 - report every dependency
            checks[name] = {"ok": False, "detail": f"{type(exc).__name__}: {exc}"[:200]}
    ok = all(c["ok"] for c in checks.values())
    if not ok:
        response.status_code = 503
    return {"status": "ready" if ok else "not ready", "checks": checks}
