"""Amazon SQS client for the demo region. boto3 is imported lazily.

Credentials come from the AWS profile (AWS_PROFILE, for example payce-fde after
`aws login`). Inside Docker, ~/.aws is mounted into the containers.
"""
from shared import settings


def sqs_client():
    import boto3

    return boto3.client("sqs", region_name=settings.AWS_REGION)


def queue_url(client, name: str | None = None) -> str:
    return client.get_queue_url(QueueName=name or settings.SQS_QUEUE_NAME)["QueueUrl"]
