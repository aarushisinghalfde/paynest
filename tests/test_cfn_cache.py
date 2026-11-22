"""Phase 10 cache stack: private, encrypted, reachable only from the app server, never in placeholder regions."""

from pathlib import Path

import yaml

from tests.test_cfn_phase3 import CfnLoader

CFN = Path(__file__).resolve().parent.parent / "infra" / "cfn" / "cache.yaml"
T = yaml.load(CFN.read_text(encoding="utf-8"), Loader=CfnLoader)
R = T["Resources"]


def test_valkey_encrypted_in_transit_and_at_rest():
    c = R["Cache"]["Properties"]
    assert c["Engine"] == "valkey" and c["TransitEncryptionEnabled"] is True and c["AtRestEncryptionEnabled"] is True
    assert T["Outputs"]["RedisUrl"]["Value"]["Sub"].startswith("rediss://")


def test_only_the_app_server_can_connect_and_only_in_private_subnets():
    ingress = R["CacheSecurityGroup"]["Properties"]["SecurityGroupIngress"]
    assert len(ingress) == 1 and ingress[0]["FromPort"] == 6379 and "CidrIp" not in ingress[0]
    assert "Ec2SecurityGroupId" in str(ingress[0]["SourceSecurityGroupId"])
    assert "PrivateSubnetIds" in str(R["CacheSubnetGroup"]["Properties"]["SubnetIds"])


def test_placeholder_regions_cannot_deploy():
    a = T["Rules"]["OnlyDeployableEnvironments"]["Assertions"][0]["Assert"]
    assert a == {"Equals": [{"Ref": "Deployable"}, "true"]}
