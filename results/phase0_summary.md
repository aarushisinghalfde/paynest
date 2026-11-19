# Phase 0 results

Run at 2026-11-19T11:13:04+00:00 by `arn:aws:sts::315549821836:assumed-role/AccountFullAccessRole/d4883488-9031-70a9-d5bf-75abaf4f163e`.

## ap-south-1

| Decision | Result |
| --- | --- |
| model ladder | DECIDE: no rung works in-region. Rungs that leave the region: none |
| starting rung | none until the ladder is decided |
| out of region rungs | none |
| embedding model | multilingual-e5 on the EC2 (no in-region Bedrock embedding passed) |
| guardrails | works: all seeded IDs masked in EN/HI/AR, injection blocked, benign passed |

| Check | Status | Detail |
| --- | --- | --- |
| model nova-micro | FAIL | AccessDeniedException: Your account is currently being verified. Verification normally takes less than 2 hours. Until your account is verified, you may not have access to this operation. If you are still receiving this message after more than 2 hours, please let us know by writing to aws-verification@amazon.com. We appreciate your patience. |
| model nova-lite | FAIL | AccessDeniedException: Your account is currently being verified. Verification normally takes less than 2 hours. Until your account is verified, you may not have access to this operation. If you are still receiving this message after more than 2 hours, please let us know by writing to aws-verification@amazon.com. We appreciate your patience. |
| model nova-2-lite | FAIL | AccessDeniedException: Your account is currently being verified. Verification normally takes less than 2 hours. Until your account is verified, you may not have access to this operation. If you are still receiving this message after more than 2 hours, please let us know by writing to aws-verification@amazon.com. We appreciate your patience. |
| model nova-pro | FAIL | AccessDeniedException: Your account is currently being verified. Verification normally takes less than 2 hours. Until your account is verified, you may not have access to this operation. If you are still receiving this message after more than 2 hours, please let us know by writing to aws-verification@amazon.com. We appreciate your patience. |
| model claude-haiku-4.5 | FAIL | AccessDeniedException: Your account is currently being verified. Verification normally takes less than 2 hours. Until your account is verified, you may not have access to this operation. If you are still receiving this message after more than 2 hours, please let us know by writing to aws-verification@amazon.com. We appreciate your patience. |
| embedding titan-embed-v2 | FAIL | in-region model, None dims, hi~hinglish None vs hi~en None |
| embedding cohere-embed-multilingual-v3 | FAIL | in-region model, None dims, hi~hinglish None vs hi~en None |
| embedding cohere-embed-v4 | FAIL | profile global.cohere.embed-v4:0, None dims, hi~hinglish None vs hi~en None |
| region_enabled | pass | opt-in-not-required |
| guardrails | pass | leaks: none; injection {'injection_blocked': True, 'benign_passed': True} |
| ec2 | pass |  |
| rds | pass | Postgres 18.3, db.t4g.micro True |
| valkey | pass | 7.2, 8.0, 8.1, 8.2, 9.0, 9.1 |
| sqs | pass |  |
| kms | pass |  |
| xray | pass |  |

## eu-central-1

| Decision | Result |
| --- | --- |
| model ladder | DECIDE: no rung works in-region. Rungs that leave the region: none |
| starting rung | none until the ladder is decided |
| out of region rungs | none |
| embedding model | multilingual-e5 on the EC2 (no in-region Bedrock embedding passed) |
| guardrails | works: all seeded IDs masked in EN/HI/AR, injection blocked, benign passed |

| Check | Status | Detail |
| --- | --- | --- |
| model nova-micro | FAIL | AccessDeniedException: Your account is currently being verified. Verification normally takes less than 2 hours. Until your account is verified, you may not have access to this operation. If you are still receiving this message after more than 2 hours, please let us know by writing to aws-verification@amazon.com. We appreciate your patience. |
| model nova-lite | FAIL | AccessDeniedException: Your account is currently being verified. Verification normally takes less than 2 hours. Until your account is verified, you may not have access to this operation. If you are still receiving this message after more than 2 hours, please let us know by writing to aws-verification@amazon.com. We appreciate your patience. |
| model nova-2-lite | FAIL | AccessDeniedException: Your account is currently being verified. Verification normally takes less than 2 hours. Until your account is verified, you may not have access to this operation. If you are still receiving this message after more than 2 hours, please let us know by writing to aws-verification@amazon.com. We appreciate your patience. |
| model nova-pro | FAIL | AccessDeniedException: Your account is currently being verified. Verification normally takes less than 2 hours. Until your account is verified, you may not have access to this operation. If you are still receiving this message after more than 2 hours, please let us know by writing to aws-verification@amazon.com. We appreciate your patience. |
| model claude-haiku-4.5 | FAIL | AccessDeniedException: Your account is currently being verified. Verification normally takes less than 2 hours. Until your account is verified, you may not have access to this operation. If you are still receiving this message after more than 2 hours, please let us know by writing to aws-verification@amazon.com. We appreciate your patience. |
| embedding titan-embed-v2 | FAIL | in-region model, None dims, hi~hinglish None vs hi~en None |
| embedding cohere-embed-multilingual-v3 | FAIL | in-region model, None dims, hi~hinglish None vs hi~en None |
| embedding cohere-embed-v4 | FAIL | profile global.cohere.embed-v4:0, None dims, hi~hinglish None vs hi~en None |
| region_enabled | pass | opt-in-not-required |
| guardrails | pass | leaks: none; injection {'injection_blocked': True, 'benign_passed': True} |
| ec2 | pass |  |
| rds | pass | Postgres 18.3, db.t4g.micro True |
| valkey | pass | 7.2, 8.0, 8.1, 8.2, 9.0, 9.1 |
| sqs | pass |  |
| kms | pass |  |
| xray | pass |  |

## Placeholder regions (not built)

| Region | Opt-in status |
| --- | --- |
| me-central-1 | not-opted-in |
