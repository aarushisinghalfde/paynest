"""PII vault: the raw values behind the <TYPE_n> tokens, encrypted, write-only for the app.

DynamoDB table (created by infra/cfn/vault.yaml in batch 3b-2):
    pk ticket_id (S), sk token (S), tenant_id, kind, ciphertext (B), expires_at (N, TTL)

Each value is encrypted on its own with the vault KMS key and the encryption context
{ticket_id, token, tenant_id}. KMS refuses to decrypt unless the same context is given,
so a reveal asked for the wrong ticket or token fails inside KMS. The EC2 role has only
kms:Encrypt and dynamodb:PutItem: it can add values but never read them back. Only the
vault-reveal Lambda has GetItem and kms:Decrypt.

Writes are append-only (a condition refuses to overwrite), so a redelivered message is
harmless and a compromised app cannot replace a stored value.
"""
import logging
import re
import time

log = logging.getLogger(__name__)

TOKEN_RE = re.compile(r"^<([A-Z_]+?)(?:_\d+)?>$")
KMS_MAX_PLAINTEXT = 4096   # bytes, a KMS Encrypt limit; ticket values are far smaller


def kind_of(token: str) -> str:
    m = TOKEN_RE.match(token)
    if not m:
        raise ValueError("not a vault token")
    return m.group(1)


def context(ticket_id: str, token: str, tenant_id: str) -> dict:
    return {"ticket_id": ticket_id, "token": token, "tenant_id": tenant_id}


class MemoryVault:
    """Laptop and tests only: values live in this process and vanish when it stops."""

    def __init__(self):
        self.items: dict[tuple[str, str], dict] = {}

    def put(self, ticket_id: str, tenant_id: str, values: dict[str, str], expires_at: int) -> int:
        written = 0
        for token, value in values.items():
            key = (ticket_id, token)
            if key not in self.items:      # append-only, like the DynamoDB condition
                self.items[key] = {"tenant_id": tenant_id, "kind": kind_of(token), "value": value,
                                   "expires_at": expires_at}
                written += 1
        return written

    def reveal(self, ticket_id: str, token: str) -> str | None:
        item = self.items.get((ticket_id, token))
        if item is None or item["expires_at"] < time.time():
            return None
        return item["value"]


class DynamoKmsVault:
    def __init__(self, table: str, key_id: str, ddb=None, kms=None, region: str | None = None):
        if ddb is None or kms is None:
            import boto3

            ddb = ddb or boto3.client("dynamodb", region_name=region)
            kms = kms or boto3.client("kms", region_name=region)
        self.table, self.key_id, self.ddb, self.kms = table, key_id, ddb, kms

    def put(self, ticket_id: str, tenant_id: str, values: dict[str, str], expires_at: int) -> int:
        written = 0
        for token, value in values.items():
            plaintext = value.encode("utf-8")
            if len(plaintext) > KMS_MAX_PLAINTEXT:
                raise ValueError(f"vault value for {kind_of(token)} is too long")
            blob = self.kms.encrypt(KeyId=self.key_id, Plaintext=plaintext,
                                    EncryptionContext=context(ticket_id, token, tenant_id))["CiphertextBlob"]
            try:
                self.ddb.put_item(
                    TableName=self.table,
                    Item={"ticket_id": {"S": ticket_id}, "token": {"S": token},
                          "tenant_id": {"S": tenant_id}, "kind": {"S": kind_of(token)},
                          "ciphertext": {"B": blob}, "expires_at": {"N": str(expires_at)}},
                    ConditionExpression="attribute_not_exists(ticket_id)",
                )
                written += 1
            except Exception as exc:  # noqa: BLE001
                if type(exc).__name__ != "ConditionalCheckFailedException":
                    raise
        return written


def from_settings(settings):
    backend = settings.VAULT_BACKEND
    if backend == "dynamo":
        return DynamoKmsVault(settings.VAULT_TABLE, settings.VAULT_KEY_ID, region=settings.AWS_REGION)
    if backend == "memory":
        log.warning("VAULT_BACKEND=memory: raw values are kept in this process only (laptop use)")
        return MemoryVault()
    raise RuntimeError("VAULT_BACKEND must be 'dynamo' (AWS) or 'memory' (laptop)")
