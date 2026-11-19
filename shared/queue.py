"""SQS client: real Amazon SQS by default, or the optional local ElasticMQ stand-in.

Real SQS uses the AWS profile (AWS_PROFILE, for example payce-fde after `aws login`);
inside Docker, ~/.aws is mounted into the containers. When SQS_ENDPOINT_URL is set,
the same code talks to ElasticMQ instead, with dummy credentials. boto3 is imported
lazily.
"""
from shared import settings


def client_kwargs() -> dict:
    kwargs = {"region_name": settings.AWS_REGION}
    if settings.SQS_ENDPOINT_URL:
        # ElasticMQ ignores credentials; fixed dummy values keep real AWS keys out of it.
        kwargs.update(endpoint_url=settings.SQS_ENDPOINT_URL,
                      aws_access_key_id="local", aws_secret_access_key="local")
    return kwargs


def sqs_client():
    import boto3

    return boto3.client("sqs", **client_kwargs())


def queue_url(client, name: str | None = None) -> str:
    return client.get_queue_url(QueueName=name or settings.SQS_QUEUE_NAME)["QueueUrl"]
