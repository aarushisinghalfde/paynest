"""Security properties of the phase 3 templates, checked without AWS."""
from pathlib import Path

import yaml

CFN = Path(__file__).resolve().parent.parent / "infra" / "cfn"
ROOT = CFN.parent.parent


class CfnLoader(yaml.SafeLoader):
    pass


def _tag(loader, suffix, node):
    if isinstance(node, yaml.ScalarNode):
        return {suffix: loader.construct_scalar(node)}
    if isinstance(node, yaml.SequenceNode):
        return {suffix: loader.construct_sequence(node, deep=True)}
    return {suffix: loader.construct_mapping(node, deep=True)}


CfnLoader.add_multi_constructor("!", _tag)


def load(name):
    return yaml.load((CFN / name).read_text(encoding="utf-8"), Loader=CfnLoader)["Resources"]


VAULT = load("vault.yaml")


def _statements(policy):
    return {s["Sid"]: s for s in policy["Statement"]}


def _actions(stmt):
    a = stmt["Action"]
    return [a] if isinstance(a, str) else a


def test_lambda_code_in_template_matches_the_tested_file():
    inline = VAULT["RevealFunction"]["Properties"]["Code"]["ZipFile"]
    source = (ROOT / "lambdas" / "vault_reveal" / "handler.py").read_text(encoding="utf-8")
    assert inline.strip() == source.strip()
    assert len(inline) < 4096          # CloudFormation's limit for inline Lambda code


def test_vault_key_admin_cannot_use_the_key():
    st = _statements(VAULT["VaultKey"]["Properties"]["KeyPolicy"])
    admin = _actions(st["AdministerButNotUse"])
    assert "kms:*" not in admin
    assert not any(a.startswith(("kms:Decrypt", "kms:Encrypt", "kms:ReEncrypt", "kms:GenerateDataKey"))
                   for a in admin)
    assert _actions(st["AppEncryptsOnly"]) == ["kms:Encrypt"]
    assert _actions(st["RevealDecryptsOnly"]) == ["kms:Decrypt"]
    for sid in ("AppEncryptsOnly", "RevealDecryptsOnly"):
        assert st[sid]["Condition"]["ForAllValues:StringEquals"]["kms:EncryptionContextKeys"] == \
            ["ticket_id", "token", "tenant_id"]


def test_ec2_role_can_only_add_values():
    st = _statements(VAULT["AppVaultPolicy"]["Properties"]["PolicyDocument"])
    allowed = [a for s in st.values() if s["Effect"] == "Allow" for a in _actions(s)]
    assert sorted(allowed) == ["dynamodb:PutItem", "kms:Encrypt"]
    denied = _actions(st["NeverReadOrChangeValues"]) + _actions(st["NeverDecrypt"])
    for a in ("dynamodb:GetItem", "dynamodb:Query", "dynamodb:Scan", "dynamodb:UpdateItem", "kms:Decrypt"):
        assert a in denied


def test_reveal_role_reads_one_item_only():
    policy = VAULT["RevealRole"]["Properties"]["Policies"][0]["PolicyDocument"]
    actions = [a for s in policy["Statement"] for a in _actions(s)]
    assert sorted(actions) == ["dynamodb:GetItem", "logs:CreateLogStream", "logs:PutLogEvents"]


def test_vault_table_has_ttl_and_is_retained():
    t = VAULT["VaultTable"]
    assert t["DeletionPolicy"] == "Retain"
    assert t["Properties"]["TimeToLiveSpecification"] == {"AttributeName": "expires_at", "Enabled": True}


def test_worker_settings_match_the_app():
    names = {r["Properties"]["Name"]["Sub"].rsplit("/", 1)[1]: r["Properties"]["Value"]
             for r in VAULT.values() if r["Type"] == "AWS::SSM::Parameter"}
    assert names["VAULT_BACKEND"] == "dynamo" and names["PII_NER"] == "required"
    assert set(names) == {"VAULT_BACKEND", "VAULT_TABLE", "VAULT_KEY_ID", "VAULT_TTL_DAYS", "PII_NER"}


def test_metric_filters_match_the_events_the_app_logs():
    obs = load("observability.yaml")
    patterns = " ".join(r["Properties"]["FilterPattern"] for r in obs.values()
                        if r["Type"] == "AWS::Logs::MetricFilter")
    for event in ("pii_blocked", "ticket_masked", "message_failed"):
        assert f'"{event}"' in patterns
    app = (ROOT / "intake" / "pipeline.py").read_text(encoding="utf-8") + \
        (ROOT / "worker" / "main.py").read_text(encoding="utf-8")
    for event in ("pii_blocked", "ticket_masked", "message_failed"):
        assert f'"{event}"' in app

def test_user_data_runs_every_boot_and_ships_logs():
    ud = load("ec2.yaml")["Instance"]["Properties"]["UserData"]["Fn::Base64"]["Sub"][0]
    assert "[scripts-user, always]" in ud
    assert '"log-driver": "awslogs"' in ud and '"mode": "non-blocking"' in ud
