"""Worker behaviour with an in-memory queue: no Docker, no AWS."""
import json

from worker.main import PROCESSED_KEY, handle, process_once, run


class FakeQueue:
    def __init__(self, bodies):
        self.messages = [{"MessageId": f"m{i}", "ReceiptHandle": f"r{i}", "Body": b}
                         for i, b in enumerate(bodies)]
        self.deleted = []

    def receive_message(self, **_):
        return {"Messages": list(self.messages)}

    def delete_message(self, QueueUrl, ReceiptHandle):  # noqa: N803 - boto3 argument names
        self.deleted.append(ReceiptHandle)


class FakeCache:
    def __init__(self):
        self.data = {}

    def set(self, key, value, ex=None):
        self.data[key] = value


def test_processes_and_deletes_each_message():
    q = FakeQueue([json.dumps({"ticket": 1}), json.dumps({"ticket": 2})])
    assert process_once(q, "url", wait_seconds=0) == 2
    assert q.deleted == ["r0", "r1"]


def test_records_check_id_so_the_gate_can_prove_delivery():
    cache = FakeCache()
    handle({"MessageId": "m1", "Body": json.dumps({"check_id": "abc"})}, cache)
    assert cache.data[PROCESSED_KEY.format("abc")] == "m1"


def test_non_json_body_is_still_handled():
    assert handle({"MessageId": "m1", "Body": "plain text"}) == {"raw": "plain text"}


def test_failed_message_is_left_for_redelivery(monkeypatch):
    q = FakeQueue([json.dumps({"ticket": 1}), json.dumps({"ticket": 2})])
    calls = []

    def flaky(message, cache=None, gate=None):
        calls.append(message["MessageId"])
        if message["MessageId"] == "m0":
            raise RuntimeError("boom")

    monkeypatch.setattr("worker.main.handle", flaky)
    process_once(q, "url", wait_seconds=0)
    assert calls == ["m0", "m1"]
    assert q.deleted == ["r1"]  # m0 stays on the queue; after 3 tries it moves to tickets-dlq


def test_empty_queue_returns_zero():
    assert process_once(FakeQueue([]), "url", wait_seconds=0) == 0


def test_queue_outage_is_retried_not_fatal():
    """A restart of the queue (e.g. ElasticMQ recreated) must not kill the worker."""
    stop = {"now": False}
    pauses = []

    class FlakyQueue(FakeQueue):
        calls = 0

        def receive_message(self, **kw):
            FlakyQueue.calls += 1
            if FlakyQueue.calls <= 2:
                raise ConnectionError("queue down")
            stop["now"] = True
            return super().receive_message(**kw)

    q = FlakyQueue([json.dumps({"ticket": 1})])
    run(q, "url", None, stop, sleep=pauses.append)
    assert pauses == [1.0, 2.0]   # backs off, then recovers
    assert q.deleted == ["r0"]
