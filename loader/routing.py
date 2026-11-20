"""Tenant routing: each tenant has a home region; a routing table says where it is served."""

from functools import lru_cache

import yaml

from shared import settings


@lru_cache(maxsize=1)
def config() -> dict:
    with open(settings.ROOT / "config" / "routing.yaml", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def home_region(country: str) -> str:
    return config()["home"][country]


def serving_region(country: str, table: str = "demo") -> str:
    return config()["tables"][table][country]


def tenants_served_here(tenants: list[dict], aws_region: str, table: str = "demo") -> list[dict]:
    """A load in one region only takes the tenants that table routes to it."""
    return [t for t in tenants if serving_region(t["region"], table) == aws_region]
