#!/usr/bin/env python3
"""Why can't this account use Bedrock (and AgentCore)? Find out exactly, in Sydney.

    $env:AWS_PROFILE = "payce-fde"
    python scripts\\check_bedrock.py
    python scripts\\check_bedrock.py --profile other-account      (any account you can sign in to)

Read-only except two tiny model calls ("reply OK", <= 5 output tokens, a fraction of a cent).
Each step prints PASS / FAIL with AWS's own error code, which says what to do next:
  AccessDeniedException ......... IAM permission or Marketplace subscription missing
  ResourceNotFoundException ..... Anthropic use-case form not submitted (console: Model catalog)
  ThrottlingException / quota 0 . new-account quota is 0: open a support case for a quota increase
  ValidationException ........... the model id / inference profile is not offered in this region
Also lists the AgentCore runtimes (read-only; kioskClassDemo is only listed, never touched).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import argparse  # noqa: E402

import boto3  # noqa: E402

REGION = "ap-southeast-2"
_session = None


def aws(service: str):
    return _session.client(service)

WANT = [("nova-micro", "Amazon Nova Micro (no form needed)"), ("claude-haiku-4-5", "Claude Haiku 4.5 (needs the Anthropic form)")]


def err(e) -> str:
    code = getattr(e, "response", {}).get("Error", {}).get("Code", type(e).__name__)
    msg = getattr(e, "response", {}).get("Error", {}).get("Message", str(e))
    return f"{code}: {msg[:160]}"


def main() -> int:
    global _session
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", help="AWS CLI profile (default: $AWS_PROFILE)")
    ap.add_argument("--region", default=REGION)
    args = ap.parse_args()
    _session = boto3.Session(profile_name=args.profile, region_name=args.region)
    ident = aws("sts").get_caller_identity()
    print("account", ident["Account"], "as", ident["Arn"].split(":")[-1], "region", args.region)
    bedrock, runtime = aws("bedrock"), aws("bedrock-runtime")

    try:
        models = bedrock.list_foundation_models()["modelSummaries"]
        print(f"PASS  list models: {len(models)} foundation models offered in {args.region}")
    except Exception as e:  # noqa: BLE001
        print("FAIL  list models:", err(e))
        return 1

    try:
        uc = bedrock.get_use_case_for_model_access()
        print("PASS  Anthropic use-case form: submitted", "(" + str(uc.get("formData", ""))[:40] + "...)" if uc else "")
    except AttributeError:
        print("SKIP  Anthropic use-case form: boto3 too old to ask (pip install -U boto3)")
    except Exception as e:  # noqa: BLE001
        print("INFO  Anthropic use-case form:", err(e))

    try:
        profiles = bedrock.list_inference_profiles(maxResults=200)["inferenceProfileSummaries"]
    except Exception as e:  # noqa: BLE001
        profiles = []
        print("INFO  inference profiles:", err(e))
    ids = [p["inferenceProfileId"] for p in profiles] + [m["modelId"] for m in models]
    for key, label in WANT:
        candidates = [i for i in ids if key in i]
        # prefer an Australia / Asia-Pacific cross-region profile, then the plain model id
        candidates.sort(key=lambda i: (not i.startswith("au."), not i.startswith("apac."), i))
        if not candidates:
            print(f"FAIL  {label}: not offered in {args.region}")
            continue
        mid = candidates[0]
        try:
            r = runtime.converse(modelId=mid, messages=[{"role": "user", "content": [{"text": "Reply with OK"}]}],
                                 inferenceConfig={"maxTokens": 5, "temperature": 0})
            text = r["output"]["message"]["content"][0]["text"]
            print(f"PASS  {label} via {mid}: answered {text!r}")
        except Exception as e:  # noqa: BLE001
            print(f"FAIL  {label} via {mid}: {err(e)}")

    # The exact ids a working Payce pilot in another free-plan account uses in Sydney (verified there by
    # direct Converse calls on 19 Nov 2026). If these pass here, Bedrock works for us too.
    print("-- ids known to work on another account in this region --")
    for mid in ("apac.amazon.nova-micro-v1:0", "apac.amazon.nova-lite-v1:0", "apac.amazon.nova-pro-v1:0",
                "amazon.nova-micro-v1:0", "au.anthropic.claude-haiku-4-5-20251001-v1:0"):
        try:
            r = runtime.converse(modelId=mid, messages=[{"role": "user", "content": [{"text": "Reply with OK"}]}],
                                 inferenceConfig={"maxTokens": 5, "temperature": 0})
            print(f"PASS  converse {mid}: {r['output']['message']['content'][0]['text']!r}")
        except Exception as e:  # noqa: BLE001
            print(f"FAIL  converse {mid}: {err(e)}")
    try:
        import json as _json
        r = runtime.invoke_model(modelId="amazon.titan-embed-text-v2:0",
                                 body=_json.dumps({"inputText": "ok", "dimensions": 256}))
        print(f"PASS  embed amazon.titan-embed-text-v2:0: {len(_json.loads(r['body'].read())['embedding'])} dims")
    except Exception as e:  # noqa: BLE001
        print(f"FAIL  embed amazon.titan-embed-text-v2:0: {err(e)}")
    try:
        quotas = aws("service-quotas").list_service_quotas(ServiceCode="bedrock", MaxResults=100)["Quotas"]
        nova = [q for q in quotas if "nova micro" in q["QuotaName"].lower() and "requests per minute" in q["QuotaName"].lower()]
        for q in nova[:3]:
            print(f"INFO  quota {q['QuotaName']}: {q['Value']}")
        if not nova:
            print(f"INFO  {len(quotas)} Bedrock quotas listed; none named for Nova Micro on-demand requests")
    except Exception as e:  # noqa: BLE001
        print("INFO  service quotas:", err(e))

    try:
        rts = aws("bedrock-agentcore-control").list_agent_runtimes()["agentRuntimes"]
        names = [r["agentRuntimeName"] for r in rts]
        print(f"PASS  AgentCore control plane: {len(rts)} runtime(s) {names} (read-only)")
    except Exception as e:  # noqa: BLE001
        print("FAIL  AgentCore control plane:", err(e))
    return 0


if __name__ == "__main__":
    sys.exit(main())
