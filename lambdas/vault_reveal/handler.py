import json
import os
import re
import time
import uuid

TOKEN = re.compile(r"^<[A-Z][A-Z_]*?(?:_\d+)?>$")
_clients = {}


def client(name):
    if name not in _clients:  # created once per Lambda container, reused across calls
        import boto3

        _clients[name] = boto3.client(name)
    return _clients[name]


def audit(**f):
    print(json.dumps({"event": "vault_reveal", **f}))


def handler(event, context, ddb=None, kms=None, now=time.time):
    ddb, kms = ddb or client("dynamodb"), kms or client("kms")
    tid = str(event.get("ticket_id", ""))
    token = str(event.get("token", ""))
    who = str(event.get("requested_by", ""))[:100]
    why = str(event.get("reason", ""))
    rid = getattr(context, "aws_request_id", None)
    try:
        uuid.UUID(tid)
    except ValueError:
        return {"status": "bad_request", "error": "ticket_id must be a UUID"}
    if not TOKEN.match(token):
        return {"status": "bad_request", "error": "token must look like <IBAN_1>"}
    if not who or len(why) < 5:
        return {"status": "bad_request", "error": "requested_by and reason are required"}
    kind = token.strip("<>").rsplit("_", 1)[0] if token[-2].isdigit() else token.strip("<>")
    item = ddb.get_item(TableName=os.environ["TABLE"], ConsistentRead=True,
                        Key={"ticket_id": {"S": tid}, "token": {"S": token}}).get("Item")
    # TTL deletion is lazy (can take days), so expiry is checked here too.
    if not item or int(item["expires_at"]["N"]) < now():
        audit(ticket_id=tid, kind=kind, requested_by=who, result="not_found", request_id=rid)
        return {"status": "not_found"}
    try:
        out = kms.decrypt(KeyId=os.environ["KEY_ARN"], CiphertextBlob=item["ciphertext"]["B"],
                          EncryptionContext={"ticket_id": tid, "token": token,
                                             "tenant_id": item["tenant_id"]["S"]})
    except Exception as exc:  # noqa: BLE001 - wrong context or key: never reveal
        audit(ticket_id=tid, kind=kind, requested_by=who, result="denied", error=type(exc).__name__,
              request_id=rid)
        return {"status": "denied"}
    audit(ticket_id=tid, kind=kind, requested_by=who, result="revealed", request_id=rid)
    return {"status": "ok", "value": out["Plaintext"].decode("utf-8")}
