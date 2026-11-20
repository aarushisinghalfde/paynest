"""JSON log lines and exception logging without messages."""
import json
import logging

from shared.logs import JsonFormatter, log_event, safe_error


def test_event_is_one_json_line():
    log = logging.getLogger("t")
    rec = []
    h = logging.Handler()
    h.emit = lambda r: rec.append(JsonFormatter().format(r))
    log.addHandler(h)
    log.setLevel(logging.INFO)
    log_event(log, "ticket_masked", ticket_id="t1", counts={"IBAN": 1})
    line = json.loads(rec[-1])
    assert line["event"] == "ticket_masked" and line["counts"] == {"IBAN": 1} and line["level"] == "INFO"
    log.removeHandler(h)


def test_safe_error_drops_the_message():
    try:
        raise ValueError('Failing row contains (Kavya, AE070331234567890123456)')
    except ValueError as exc:
        info = safe_error(exc)
    assert info["error"] == "ValueError" and info["where"].startswith("test_logs.py:")
    assert "Kavya" not in json.dumps(info)
