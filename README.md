# AI gateway and tool-calling agent

![CI](https://github.com/lyftium/agent-gateway-stack/actions/workflows/ci.yml/badge.svg)

Clients often reimplement API keys, quotas, and routing around every model service, while a tool-calling loop needs a boundary before side effects. I built two small FastAPI services to investigate those boundaries: an OpenAI-compatible gateway and an agent restricted to typed, allowlisted tools.

This is a demonstrator, not an authorization system for real side effects. The agent stops on an approval-required call, and the approvals endpoint records an accepted intent in an in-memory accept-once ledger. It does not execute a real queue job or automatically resume a run, and the endpoint has no separate operator authentication beyond the supplied operator string and the demo service's deployment boundary.

I tested the services on local Kind with a mock model. Measurements describe gateway overhead over that instant backend, not real inference performance. [Walkthrough](docs/DEMO.md).

## Example

The Compose stack runs `agent → gateway → mock-llm` with development-only keys:

```bash
docker compose up --build
curl -s localhost:8000/v1/agent/runs -H 'content-type: application/json' \
  -d '{"task": "Air density at 11000 m in the ISA model?"}'
# Stop with: docker compose down
```

Expected response excerpt:

```json
{
  "status": "completed",
  "answer": "Computed result: {\"result\": {\"altitude_m\": 11000.0, \"temperature_k\": 216.65, \"pressure_pa\": 22632.0, \"density_kg_m3\": 0.36392, \"speed_of_sound_m_s\": 295.07}}",
  "steps": [{
    "tool": "isa_atmosphere",
    "arguments": {"altitude_m": 11000.0},
    "outcome": "ok",
    "result": {"density_kg_m3": 0.36392, "speed_of_sound_m_s": 295.07}
  }]
}
```

Run ids, timings, usage, and other fields vary. The keyword-driven mock returns the computed tool result verbatim; it is a test double, not a language model evaluating tool-calling quality.

## Quickstart without containers

Python 3.11+, `make`, and a CPU are sufficient for unit/integration tests:

```bash
python -m venv .venv && . .venv/bin/activate
python -m pip install -e '.[dev]'
pytest -q
```

Expected: tests pass with no model download. Optional `make validate` also requires `kubectl`, `kubeconform`, `kustomize`, `jsonschema`, network access for its small CRD schema downloads, and the prerequisites detailed in [`docs/DEMO.md`](docs/DEMO.md).

## What I implemented

### Gateway

- SHA-256 tenant-key identities, per-model allowlists, and request token caps.
- In-memory **per-replica** request/token buckets. Token usage is charged after the upstream response, so concurrent requests can overdraw a budget; this is not a globally coordinated limiter.
- Ordered-upstream failover on connection/5xx errors, streaming byte relay, usage accounting, request ids, metrics, and no prompt-content logging in the implemented paths.
- Local Kind and container packaging, with committed CI and manifest checks.

### Agent

- Closed tool registry, typed argument validation, timeouts, and a bounded model-call loop.
- Read-only calculation tools for ISA atmosphere, unit conversion, and tolerance stack-ups.
- `awaiting_approval` before the only side-effect-shaped tool, followed by an idempotent demo approval record.
- Selected bounded prompt-injection tests: unknown/disallowed calls and side-effect gating, not a comprehensive security assessment.

[Architecture/design](docs/design.md) · [Agent loop](docs/agent.md) · [Security-test boundary](docs/security-tests.md)

## Measured gateway overhead

Against an instant mock on one Apple M1 Pro, one uvicorn worker per service, 1,500 requests per repetition and median of three repetitions ([method](docs/benchmark.md)):

| Mode | Concurrency | Direct p50 | Through gateway p50 | Added |
|---|---:|---:|---:|---:|
| non-stream | 1 | 1.03 ms | 2.67 ms | +1.65 ms |
| stream | 1 | 1.55 ms | 3.09 ms | +1.54 ms |
| stream | 8 | 7.50 ms | 15.28 ms | +7.78 ms |

A byte-forwarding relay improved the recorded concurrency-8 streaming cell versus the previous re-serializing implementation. At concurrency 32 the local single worker was saturated and results were noisy. These measurements cannot be used as real-model inference latency or cluster capacity estimates.

## Design decisions

1. **The service, not the model, controls tool access.** The allowlist, schemas, limits, and approval stop live in application code rather than prompt instructions.
2. **Approval is explicit but scoped to the demo.** Accept-once semantics are testable without simulating a real queue or claiming independent operator identity.
3. **Relay bytes, inspect only metadata.** Forwarding the original SSE bytes avoids needless serialization while still allowing usage and timing observations.

## Packaging

`deploy/base/` contains the gateway/agent manifests; `deploy/overlays/kind/` adds the local mock and development secret. Containers use non-root users, read-only root filesystems, dropped capabilities, and `RuntimeDefault` seccomp profiles. Development keys in the Compose/Kind files are public demo fixtures only: do not reuse them for a real service or expose this demo stack to untrusted users.

The additional cluster overlays have not been applied to a GPU-backed cluster. The recorded deployment and approval transcript is under [`docs/evidence/kind-apply/`](docs/evidence/kind-apply/); use [`docs/DEMO.md`](docs/DEMO.md) for runnable local paths rather than treating every overlay command as tested.

## Limitations

- Per-replica, in-memory quotas and approval ledger; no shared durable state.
- No independent operator authentication on approvals and no real side-effect execution.
- Mock-backend overhead only; no real-model tool-calling accuracy evaluation.
- Selected injection/refusal tests do not establish comprehensive security.
- Local Kind evidence and manifest schema checks are not a production deployment.

[Quickstart](docs/DEMO.md) · [Benchmark method](docs/benchmark.md) · [Verification boundary](docs/vnv.md) · [MIT license](LICENSE)
