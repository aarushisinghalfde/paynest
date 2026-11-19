# infra

- `local/elasticmq.conf`: the OPTIONAL local stand-in for SQS (offline work only).
  Real SQS in Sydney is the default; see the README.
- `cfn/`: CloudFormation templates, one stack per file (`network.yaml` first), deployed
  with `scripts\cfn.ps1`. `params/demo.json` (Sydney) is the only deployable environment;
  `params/india.json` and `params/uae.json` are placeholders that the templates refuse to
  deploy. Development queues are created by `scripts/create_dev_queues.py`.
