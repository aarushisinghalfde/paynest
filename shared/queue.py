"""SQS client: ElasticMQ locally, Amazon SQS in AWS. boto3 is imported lazily."""
from shared import settings


def sqs_client():
    import boto3

    kwargs = {"region_name": settings.AWS_REGION}
    if settings.SQS_ENDPOINT_URL:
        # ElasticMQ ignores credentials; fixed dummy values keep real AWS keys out of local runs.
        kwargs.update(endpoint_url=settings.SQS_ENDPOINT_URL,
                      aws_access_key_id="local", aws_secret_access_key="local")
    return boto3.client("sqs", **kwargs)


def queue_url(client, name: str | None = None) -> str:
    return client.get_queue_url(QueueName=name or settings.SQS_QUEUE_NAME)["QueueUrl"]
