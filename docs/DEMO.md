# Demo — AI gateway & tool-calling agent

Run the unit/integration suite or a local Compose stack against a mock LLM. This demonstrates plumbing and boundaries, not tool-calling quality with a real model.

## Prerequisites

- Python 3.11+, `make`, pip
- Optional local stack: Docker with Compose
- Optional manifest validation: `kubectl`, `kustomize`, `kubeconform`, the Python `jsonschema` package, and network access for the small CRD schema downloads listed in the [`Makefile`](../Makefile)
- Optional local cluster: Kind; the public Compose demo needs no Kubernetes cluster

## Tests

```bash
python -m venv .venv && . .venv/bin/activate
python -m pip install -e '.[dev]'
pytest -q
```

Expected: auth, quota, failover, allowlist, approval, tool, and selected injection-posture tests pass. Do not quote a static test count; inspect the run at the current commit.

## Local Compose request/response

```bash
docker compose up --build
```

In another shell:

```bash
curl -s localhost:8000/v1/agent/runs -H 'content-type: application/json' \
  -d '{"task": "Air density at 11000 m in the ISA model?"}'
```

Expected: `status` is `completed`; `steps[0].result.density_kg_m3` is `0.36392`; the mock answer contains the computed result. Shutdown:

```bash
docker compose down
```

The Compose and Kind development keys are public local-demo fixtures. They are not credentials for a deployed service.

## Approval behavior

A side-effect-shaped tool stops with `awaiting_approval`. `POST /v1/agent/approvals` records one accepted fingerprint and a duplicate on a repeat. This demonstrator:

- has no separate operator authentication beyond the service's deployment/demo boundary;
- records an accepted queue intent rather than executing a real job;
- does not automatically resume the paused agent run;
- stores approvals in memory, so they are per replica and disappear on restart.

See the [recorded Kind transcript](evidence/kind-apply/agent-run-20261104-190455.txt) for an example.

## Optional manifest validation

Install the prerequisites above, then:

```bash
python -m pip install jsonschema
make validate
```

Expected: manifest and explicit CRD checks finish without validation errors. The target downloads published schema files into `.cache/crds/` and performs no cluster apply. Review the Makefile to see the exact remote schema versions.

## Optional Kind

With Docker, `kubectl`, and Kind installed, inspect the base/overlay manifests and use the repository's [Kind smoke notes](evidence/kind-smoke-2026-11-04.md) and transcripts as the recorded environment. The transcripts are evidence of prior stub/mock runs, not live instructions that provision a cluster without your review.

## Limitations

- Mock backend; overhead is not real inference performance.
- Per-replica in-memory quotas and approvals can be overdrawn under concurrent requests; token accounting occurs after the upstream response.
- Approval is a demo queue-intent boundary, not authenticated production authorization.
- No real-model tool-accuracy result or GPU-backed deployment.
- Selected prompt-injection tests are not a comprehensive security evaluation.
