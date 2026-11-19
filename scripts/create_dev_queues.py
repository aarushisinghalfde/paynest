#!/usr/bin/env python3
"""Create the development queues in Sydney (real Amazon SQS).

    aws login --profile payce-fde --remote
    python scripts/create_dev_queues.py

Creates paynest-dev-tickets-dlq and paynest-dev-tickets-in. A message that fails
3 times moves to the DLQ. Long polling (20 s) keeps an idle worker to about
130,000 requests a month, inside the SQS free tier of 1 million. Safe to re-run.
Phase 2 creates the production queues with Terraform.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shared import settings  # noqa: E402

DLQ_NAME = settings.SQS_QUEUE_NAME.replace("tickets-in", "tickets-dlq")
TAGS = {"project": "payce", "env": "dev"}


def main_queue_attributes(dlq_arn: str) -> dict:
    return {
        "RedrivePolicy": json.dumps({"deadLetterTargetArn": dlq_arn, "maxReceiveCount": "3"}),
        "ReceiveMessageWaitTimeSeconds": "20",
        "VisibilityTimeout": "60",
        "MessageRetentionPeriod": str(4 * 24 * 3600),
    }


def main() -> int:
    from botocore.exceptions import ClientError

    from shared.queue import sqs_client

    sqs = sqs_client()
    dlq_url = sqs.create_queue(QueueName=DLQ_NAME, tags=TAGS,
                               Attributes={"MessageRetentionPeriod": str(14 * 24 * 3600)})["QueueUrl"]
    dlq_attrs = sqs.get_queue_attributes(QueueUrl=dlq_url, AttributeNames=["QueueArn"])
    dlq_arn = dlq_attrs["Attributes"]["QueueArn"]
    try:
        url = sqs.create_queue(QueueName=settings.SQS_QUEUE_NAME, tags=TAGS,
                               Attributes=main_queue_attributes(dlq_arn))["QueueUrl"]
    except ClientError as exc:
        # The queue exists with different attributes: update them instead.
        if exc.response["Error"]["Code"] not in ("QueueNameExists", "QueueAlreadyExists"):
            raise
        url = sqs.get_queue_url(QueueName=settings.SQS_QUEUE_NAME)["QueueUrl"]
        sqs.set_queue_attributes(QueueUrl=url, Attributes=main_queue_attributes(dlq_arn))
    print(f"region {settings.AWS_REGION}\n  queue {url}\n  DLQ   {dlq_url}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
