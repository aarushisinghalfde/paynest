"""Migration ordering and the dev-queue settings: no database or AWS needed."""
import json
from pathlib import Path

from scripts.create_dev_queues import DLQ_NAME, main_queue_attributes
from scripts.migrate import MIGRATIONS_DIR, pending


def test_pending_skips_applied_and_sorts_by_name():
    files = [Path("003_c.sql"), Path("001_a.sql"), Path("002_b.sql")]
    assert [f.name for f in pending(files, {"001_a.sql"})] == ["002_b.sql", "003_c.sql"]


def test_nothing_pending_when_all_applied():
    files = [Path("001_a.sql")]
    assert pending(files, {"001_a.sql"}) == []


def test_migration_files_are_numbered():
    names = [f.name for f in MIGRATIONS_DIR.glob("*.sql")]
    assert names, "expected at least one migration"
    assert all(n[:3].isdigit() and n[3] == "_" for n in names)


def test_dev_queue_moves_messages_to_dlq_after_three_tries():
    attrs = main_queue_attributes("arn:aws:sqs:ap-southeast-2:665651551863:paynest-dev-tickets-dlq")
    policy = json.loads(attrs["RedrivePolicy"])
    assert policy["maxReceiveCount"] == "3"
    assert policy["deadLetterTargetArn"].endswith("tickets-dlq")
    assert attrs["ReceiveMessageWaitTimeSeconds"] == "20"  # long polling keeps SQS in the free tier


def test_dlq_name_follows_the_main_queue():
    assert DLQ_NAME.endswith("tickets-dlq")
