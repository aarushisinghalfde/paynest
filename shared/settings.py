"""Settings shared by the API, worker and scripts.

Values come from environment variables. On a laptop they are read from .env
(see .env.example); inside Docker Compose they are set in docker-compose.yml.
"""
import os
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent

try:  # .env is optional
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except ImportError:  # pragma: no cover
    pass


def _env(name: str, default: str) -> str:
    value = os.environ.get(name)
    return value if value else default


# Which config/regions/<name>.yaml this process serves. "demo" is Sydney.
REGION = _env("PAYNEST_REGION", "demo")

DATABASE_URL = _env("DATABASE_URL", "postgresql://paynest:paynest@localhost:5433/paynest")
VALKEY_URL = _env("VALKEY_URL", "redis://localhost:6380/0")

# Local runs point SQS at ElasticMQ; in AWS this is left empty and real SQS is used.
SQS_ENDPOINT_URL = os.environ.get("SQS_ENDPOINT_URL", "http://localhost:9324")
SQS_QUEUE_NAME = _env("SQS_QUEUE_NAME", "tickets-in")

RESULTS_DIR = ROOT / "results"


def load_region(name: str | None = None) -> dict:
    path = ROOT / "config" / "regions" / f"{name or REGION}.yaml"
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


REGION_CONFIG = load_region()
# The region config is the single source of truth, so a stray AWS_REGION on the
# laptop can never point this process at the wrong region.
AWS_REGION = REGION_CONFIG["aws_region"]
