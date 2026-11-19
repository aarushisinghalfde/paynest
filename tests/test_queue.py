"""Queue client settings: real SQS by default, ElasticMQ only when asked."""
from pathlib import Path

from shared import queue, settings

ROOT = Path(__file__).resolve().parent.parent


def test_real_sqs_by_default(monkeypatch):
    monkeypatch.setattr(settings, "SQS_ENDPOINT_URL", "")
    kwargs = queue.client_kwargs()
    assert kwargs == {"region_name": "ap-southeast-2"}  # no endpoint, no dummy keys


def test_local_endpoint_uses_dummy_credentials(monkeypatch):
    monkeypatch.setattr(settings, "SQS_ENDPOINT_URL", "http://localhost:9324")
    kwargs = queue.client_kwargs()
    assert kwargs["endpoint_url"] == "http://localhost:9324"
    assert kwargs["aws_access_key_id"] == "local"  # real AWS keys never reach ElasticMQ


def test_local_queue_matches_the_dev_queues():
    conf = (ROOT / "infra" / "local" / "elasticmq.conf").read_text(encoding="utf-8")
    assert "paynest-dev-tickets-in" in conf and "paynest-dev-tickets-dlq" in conf
    assert "maxReceiveCount = 3" in conf
