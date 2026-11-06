# Demo — AI gateway and tool-calling agent

Run the tests against the mock model. This does not measure a real inference server.

## Prerequisites

- Python 3.11+
- `make validate` needs `kubectl`, `kustomize`, and `kubeconform`
- Optional: Docker, for Compose or Kind

## Quickstart

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
python -m pytest -q
make validate
```

**Expected:** allowlist, approve-once, and ISA tests pass. Manifest validation reports the checked overlays as valid.

## Optional — Compose

```bash
docker compose up --build
curl -s localhost:8000/v1/agent/runs -H 'content-type: application/json' \
  -d '{"task": "Air density at 11000 m in the ISA model?"}'
docker compose down
```

The response is the mock agent’s JSON for that task. Prior Kind evidence: [`docs/evidence/kind-apply/`](evidence/kind-apply/).

## Limitations

The approval call records a queue intent. It does not log an operator in, and it does not execute a real job. Quotas are per replica. Kind uses a mock model. The OpenShift overlay has not been applied.
