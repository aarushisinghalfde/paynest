"""Phase D infra: the server's compose gains an X-Ray collector; the role may write traces."""
import re
from pathlib import Path

import yaml

from tests.test_cfn_phase3 import CfnLoader

CFN = Path(__file__).resolve().parent.parent / "infra" / "cfn"


def _userdata() -> str:
    t = yaml.load((CFN / "ec2.yaml").read_text(encoding="utf-8"), Loader=CfnLoader)
    sub = t["Resources"]["Instance"]["Properties"]["UserData"]["Fn::Base64"]["Sub"][0]
    return re.sub(r"\$\{[^}]+\}", "X", sub)  # CloudFormation substitutions -> placeholder


def _heredoc(text: str, marker: str) -> dict:
    body = re.search(rf"<<'{marker}'\n(.*?)\n\s*{marker}\n", text, re.S).group(1)
    indent = min(len(line) - len(line.lstrip()) for line in body.splitlines() if line.strip())
    return yaml.safe_load("\n".join(line[indent:] for line in body.splitlines()))


def test_worker_sends_spans_to_the_collector_and_the_collector_exports_to_xray():
    ud = _userdata()
    compose = _heredoc(ud, "YML")
    worker, collector = compose["services"]["worker"], compose["services"]["otel-collector"]
    assert worker["environment"]["OTEL_EXPORTER_OTLP_ENDPOINT"] == "http://otel-collector:4318"
    assert "aws-otel-collector" in collector["image"] and "ports" not in collector  # not reachable from outside
    otel = _heredoc(ud, "OTEL")
    assert otel["service"]["pipelines"]["traces"]["exporters"] == ["awsxray"]
    assert "ticket_id" in otel["exporters"]["awsxray"]["indexed_attributes"]


def test_instance_role_can_write_traces_only():
    t = yaml.load((CFN / "iam.yaml").read_text(encoding="utf-8"), Loader=CfnLoader)
    stmts = t["Resources"]["Ec2Role"]["Properties"]["Policies"][0]["PolicyDocument"]["Statement"]
    xray = next(s for s in stmts if s.get("Sid") == "WriteTraces")
    assert all(a.startswith("xray:Put") or a.startswith("xray:GetSampling") for a in xray["Action"])


def test_ready_names_the_cache_backend_without_the_host_or_token():
    from shared.deps import redis_kind

    assert redis_kind("rediss://paynest-demo-cache.abc123.apse2.cache.amazonaws.com:6379/0") == "ElastiCache Valkey"
    assert redis_kind("rediss://default:secret@fine-cat-1234.upstash.io:6379") == "Upstash"
    assert redis_kind("redis://localhost:6379") == "Redis"
