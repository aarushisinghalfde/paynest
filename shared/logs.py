"""Structured JSON logs: one JSON object per line, ready for CloudWatch Logs metric filters.

    from shared.logs import log_event, safe_error
    log_event(log, "ticket_masked", ticket_id=tid, counts={"IBAN": 1}, ms=12.3)

Rule: log ids, kinds, counts and timings, never values. Exceptions are logged with
safe_error(): the exception type and the code location only. Exception messages are
dropped on purpose, because some quote data (a Postgres error can include the failing
row, for example a ticket body).
"""
import json
import logging
import re
import traceback

_RESERVED = set(vars(logging.LogRecord("", 0, "", 0, "", (), None)))


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        out = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
        }
        fields = getattr(record, "fields", None)
        if fields:
            out.update(fields)
        else:
            out["msg"] = record.getMessage()
        for key, value in vars(record).items():  # anything passed through extra={...}
            if key not in _RESERVED and key not in ("fields", "message") and key not in out:
                out[key] = value
        return json.dumps(out, ensure_ascii=False, default=str)


def configure(level: int = logging.INFO) -> None:
    """Send every log line to stderr as JSON (the containers' stdout/stderr)."""
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)


def log_event(logger: logging.Logger, event: str, level: int = logging.INFO, **fields) -> None:
    logger.log(level, event, extra={"fields": {"event": event, **fields}})


def safe_error(exc: BaseException) -> dict:
    """Exception type and where it happened (file:line of the innermost frame), no message."""
    frames = traceback.extract_tb(exc.__traceback__)
    name = re.split(r"[\\/]", frames[-1].filename)[-1] if frames else ""  # Windows and Linux paths
    where = f"{name}:{frames[-1].lineno}" if frames else None
    return {"error": type(exc).__name__, "where": where}
