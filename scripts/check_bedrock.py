#!/usr/bin/env python3
"""Why can't this account use Bedrock (and AgentCore)? Find out exactly, in Sydney.

    $env:AWS_PROFILE = "payce-fde"
    python scripts\\check_bedrock.py

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

from scripts.phase4_remote import REGION, aws, check_account  # noqa: E402

WANT = [("nova-micro", "Amazon Nova Micro (no form needed)"), ("claude-haiku-4-5", "Claude Haiku 4.5 (needs the Anthropic form)")]


def err(e) -> str:
    code = getattr(e, "response", {}).get("Error", {}).get("Code", type(e).__name__)
    msg = getattr(e, "response", {}).get("Error", {}).get("Message", str(e))
    return f"{code}: {msg[:160]}"


def main() -> int:
    print("account", check_account(), "region", REGION)
    bedrock, runtime = aws("bedrock"), aws("bedrock-runtime")

    try:
        models = bedrock.list_foundation_models()["modelSummaries"]
        print(f"PASS  list models: {len(models)} foundation models offered in {REGION}")
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
            print(f"FAIL  {label}: not offered in {REGION}")
            continue
        mid = candidates[0]
        try:
            r = runtime.converse(modelId=mid, messages=[{"role": "user", "content": [{"text": "Reply with OK"}]}],
                                 inferenceConfig={"maxTokens": 5, "temperature": 0})
            text = r["output"]["message"]["content"][0]["text"]
            print(f"PASS  {label} via {mid}: answered {text!r}")
        except Exception as e:  # noqa: BLE001
            print(f"FAIL  {label} via {mid}: {err(e)}")

    try:
        rts = aws("bedrock-agentcore-control").list_agent_runtimes()["agentRuntimes"]
        names = [r["agentRuntimeName"] for r in rts]
        print(f"PASS  AgentCore control plane: {len(rts)} runtime(s) {names} (read-only)")
    except Exception as e:  # noqa: BLE001
        print("FAIL  AgentCore control plane:", err(e))
    return 0


if __name__ == "__main__":
    sys.exit(main())
