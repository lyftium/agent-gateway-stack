# Demo — AI gateway & tool-calling agent

Run unit tests and (optionally) Kind against a mock LLM. No claim of tool-calling quality with a real model.

## Prerequisites

- Python 3.10+, `make`
- Optional: Docker, Kind

## Quickstart

```bash
python -m pytest -q
make validate
```

**Expected:** allowlist / approve-once / ISA tests pass; manifests validate.

## Optional — Kind

See the README Deploy section. Prior Kind evidence (Ready + agent-run): [`docs/evidence/kind-apply/`](evidence/kind-apply/).

## Limitations

- Kind uses a **mock-llm**
- OpenShift AI overlays are prepared, not live-applied on GPU
- Quotas are per-replica today
- No real-model tool-accuracy claim
