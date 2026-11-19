"""Queue worker.

Phase 1: receive messages from the tickets queue, log them, and delete them. Messages
that fail are left on the queue, so SQS redelivers them and moves them to the
dead-letter queue after 3 attempts.

Phase 5 replaces handle() with the LangGraph run, and a message is then deleted only
after the run has reached a checkpoint.

Run:  python -m worker.main
"""
import json
import logging
import signal
import time

from shared import settings
from shared.queue import queue_url, sqs_client

log = logging.getLogger("worker")
PROCESSED_KEY = "worker:processed:{}"  # used by scripts/check_phase1.py to prove delivery


def handle(message: dict, cache=None) -> dict:
    try:
        body = json.loads(message["Body"])
    except (json.JSONDecodeError, TypeError):
        body = {"raw": message.get("Body")}
    log.info("received message %s: %s", message.get("MessageId"), body)
    check_id = body.get("check_id") if isinstance(body, dict) else None
    if cache is not None and check_id:
        cache.set(PROCESSED_KEY.format(check_id), message.get("MessageId", ""), ex=600)
    return body


def process_once(client, url: str, cache=None, wait_seconds: int = 20) -> int:
    """Receive one batch; delete each message only if handle() succeeded."""
    resp = client.receive_message(QueueUrl=url, MaxNumberOfMessages=10, WaitTimeSeconds=wait_seconds)
    messages = resp.get("Messages", [])
    for message in messages:
        try:
            handle(message, cache)
        except Exception:  # noqa: BLE001 - leave it for redelivery
            log.exception("failed to handle %s; leaving it for redelivery", message.get("MessageId"))
            continue
        client.delete_message(QueueUrl=url, ReceiptHandle=message["ReceiptHandle"])
    return len(messages)


def wait_for_queue(client, attempts: int = 30, delay: float = 2.0) -> str:
    for attempt in range(1, attempts + 1):
        try:
            return queue_url(client)
        except Exception as exc:  # noqa: BLE001
            log.info("queue not ready (%s/%s): %s", attempt, attempts, type(exc).__name__)
            time.sleep(delay)
    raise RuntimeError(f"queue {settings.SQS_QUEUE_NAME} not reachable in {settings.AWS_REGION}: "
                       "check `aws login` and scripts/create_dev_queues.py")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    stop = {"now": False}

    def _stop(*_):
        stop["now"] = True
        log.info("stopping after the current batch")

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    import redis

    client = sqs_client()
    url = wait_for_queue(client)
    if not settings.REDIS_URL:
        raise RuntimeError("REDIS_URL is not set: add your Upstash URL to .env")
    cache = redis.Redis.from_url(settings.REDIS_URL)
    log.info("worker listening on %s", url)
    while not stop["now"]:
        process_once(client, url, cache)


if __name__ == "__main__":
    main()
