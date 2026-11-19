# infra

- `local/elasticmq.conf`: the OPTIONAL local stand-in for SQS (offline work only).
  Real SQS in Sydney is the default; see the README.
- Terraform for Sydney (`demo.tfvars`) and the placeholder production regions
  (`india.tfvars`, `uae.tfvars`) is added in phase 2, including the production SQS
  queues. Development queues are created by `scripts/create_dev_queues.py`.
