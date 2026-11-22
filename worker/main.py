"""Queue worker.

Phase 1: receive messages from the tickets queue and delete them once handled. Messages
that fail are left on the queue, so SQS redelivers them and moves them to the
dead-letter queue after 3 attempts.

Phase 3: a {"ticket_id": ...} message runs the PII gate (intake/pipeline.py) before
anything else reads the ticket. Logs are JSON lines with ids, kinds and counts only.

Phase 5 replaces handle() with the LangGraph run, and a message is then deleted only
after the run has reached a checkpoint.

Run:  python -m worker.main
"""

import json
import logging
import signal
import time

from shared import settings
from shared.logs import configure, log_event, safe_error
from shared.queue import queue_url, sqs_client

log = logging.getLogger("worker")
PROCESSED_KEY = "worker:processed:{}"  # used by scripts/check_phase1.py to prove delivery


def handle(message: dict, cache=None, gate=None) -> dict:
    """gate(ticket_id) runs the PII gate; it raises to leave the message for redelivery."""
    try:
        body = json.loads(message["Body"])
    except (json.JSONDecodeError, TypeError):
        body = {"raw": message.get("Body")}
    # Log the message's keys, never its contents.
    keys = sorted(body) if isinstance(body, dict) else []
    log_event(log, "message_received", message_id=message.get("MessageId"), keys=keys)
    if not isinstance(body, dict):
        return body
    if body.get("ticket_id"):
        if gate is None:
            raise RuntimeError("ticket message but the PII gate is not configured")
        gate(str(body["ticket_id"]))
    check_id = body.get("check_id")
    if cache is not None and check_id:
        cache.set(PROCESSED_KEY.format(check_id), message.get("MessageId", ""), ex=600)
    return body


def process_once(client, url: str, cache=None, wait_seconds: int = 20, gate=None) -> int:
    """Receive one batch; delete each message only if handle() succeeded."""
    resp = client.receive_message(QueueUrl=url, MaxNumberOfMessages=10, WaitTimeSeconds=wait_seconds)
    messages = resp.get("Messages", [])
    for message in messages:
        try:
            handle(message, cache, gate)
        except Exception as exc:  # noqa: BLE001 - leave it for redelivery
            # Type and location only: an exception message can quote ticket text.
            log_event(
                log, "message_failed", logging.ERROR, message_id=message.get("MessageId"), **safe_error(exc)
            )
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
    raise RuntimeError(
        f"queue {settings.SQS_QUEUE_NAME} not reachable in {settings.AWS_REGION}: "
        "check `aws login` and scripts/create_dev_queues.py"
    )


def run(client, url: str, cache, stop: dict, sleep=time.sleep, gate=None) -> None:
    """Poll until stopped. A queue outage (restart, network blip) is logged and retried
    with a growing pause, instead of crashing the worker."""
    delay = 1.0
    while not stop["now"]:
        try:
            process_once(client, url, cache, gate=gate)
            delay = 1.0
        except Exception as exc:  # noqa: BLE001 - keep polling; messages stay safe on the queue
            log.warning("queue unavailable (%s); retrying in %.0fs", type(exc).__name__, delay)
            sleep(delay)
            delay = min(delay * 2, 30.0)


def build_gate():
    """The agent with its real store, vault and Postgres checkpoints. Fails fast on missing configuration.

    gate(ticket_id) runs (or resumes) the ticket's graph: pii_gate first, then the other
    nodes, checkpointed after each one. It raises on failure so the message is redelivered.
    """
    from agent import graph as agent_graph
    from agent.nodes import Deps
    from agent.store import PgAgentStore
    from intake.vault import from_settings
    from pii import presidio_layer

    if not settings.PII_HMAC_KEY:
        raise RuntimeError("PII_HMAC_KEY is not set: see .env.example")
    presidio_layer.get_analyzer()  # PII_NER=required raises here, not on the first ticket
    from agent.classifier import Classifier, similar_from_db
    from agent.models import ModelClient, PgLedger, config

    client = ModelClient(ledger=PgLedger(settings.DATABASE_URL))
    classifier = Classifier(similar_from_db(settings.DATABASE_URL), client if client.key else None,
                            rung=config().get("defaults", {}).get("classify", 0))
    store = PgAgentStore(settings.DATABASE_URL)
    retriever = None
    if settings.DRAFTING == "on":
        from agent.retrieval import Retriever

        chunks, rules = store.knowledge()
        examples = store.resolved_examples()  # past questions and the KB article that solved each
        retriever = Retriever(chunks, rules, examples=examples)
        log_event(log, "knowledge_loaded", chunks=len(chunks), rules=len(rules), resolved_examples=len(examples))
    answer_cache = None
    if retriever is not None and settings.REDIS_URL:
        import redis

        from agent.answer_cache import RedisAnswerCache

        answer_cache = RedisAnswerCache(redis.Redis.from_url(settings.REDIS_URL, socket_timeout=2))
    deps = Deps(store, from_settings(settings), settings.PII_HMAC_KEY.encode(),
                settings.VAULT_TTL_DAYS, classifier=classifier, retriever=retriever, answer_cache=answer_cache,
                model=client if client.key else None, payroll_url=settings.PAYROLL_API_URL,
                draft_rung=config().get("defaults", {}).get("draft", 1))
    graph = agent_graph.build(deps, agent_graph.postgres_checkpointer(settings.DATABASE_URL))
    reload = knowledge_reloader(deps, store) if retriever is not None else (lambda: None)

    def gate(ticket_id):
        reload()  # pick up imported or withdrawn articles (checked at most once a minute)
        return agent_graph.run(graph, ticket_id)

    return gate


def knowledge_reloader(deps, store, every: float = 60.0, clock=time.monotonic):
    """Rebuild the retriever from the database when the knowledge changed (phase B imports).

    The graph holds `deps`, so swapping deps.retriever takes effect on the next ticket. The new
    KB version also starts a fresh answer-cache bucket, so no stale cached answer is reused.
    A failed check keeps the current knowledge and tries again a minute later.
    """
    from agent.retrieval import Retriever

    state = {"stamp": store.knowledge_stamp(), "checked": clock()}

    def reload():
        if clock() - state["checked"] < every:
            return
        state["checked"] = clock()
        try:
            stamp = store.knowledge_stamp()
            if stamp == state["stamp"]:
                return
            chunks, rules = store.knowledge()
            deps.retriever = Retriever(chunks, rules, examples=store.resolved_examples())
            state["stamp"] = stamp
            log_event(log, "knowledge_reloaded", chunks=len(chunks), kb_version=deps.retriever.version)
        except Exception as exc:  # noqa: BLE001 - keep answering with what we have
            log_event(log, "knowledge_reload_failed", logging.WARNING, **safe_error(exc))

    return reload


def main() -> None:
    configure()
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
    gate = build_gate()
    log.info("worker listening on %s", url)
    run(client, url, cache, stop, gate=gate)


if __name__ == "__main__":
    main()
