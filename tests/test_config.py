"""Region and model configuration."""
from pathlib import Path

import pytest
import yaml

from shared import settings

ROOT = Path(__file__).resolve().parent.parent


def test_demo_region_is_sydney_and_built():
    demo = settings.load_region("demo")
    assert demo["aws_region"] == "ap-southeast-2"
    assert demo["placeholder"] is False


@pytest.mark.parametrize("name,region", [("india", "ap-south-1"), ("uae", "me-central-1")])
def test_production_regions_are_placeholders(name, region):
    cfg = settings.load_region(name)
    assert cfg["aws_region"] == region
    assert cfg["placeholder"] is True


def test_model_ladder_is_set_for_the_active_provider():
    cfg = yaml.safe_load((ROOT / "config" / "models.yaml").read_text(encoding="utf-8"))
    assert cfg["providers"][cfg["provider"]]["ladder"], "the active provider needs at least one rung"


def test_first_migration_creates_both_extensions():
    text = (ROOT / "db" / "migrations" / "001_extensions.sql").read_text(encoding="utf-8")
    assert "CREATE EXTENSION IF NOT EXISTS vector" in text
    assert "CREATE EXTENSION IF NOT EXISTS pg_trgm" in text
