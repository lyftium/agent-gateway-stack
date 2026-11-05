# Kind smoke — agent-gateway-stack — 2026-11-04 (America/Los_Angeles)

Cluster: shared Kind `drw`. Image: `agent-gateway-stack:dev` retagged from GHCR digest `sha256:660b84b00aa62e883af7c5f487b312c7919d69000b1d4ad2f52a1f9ffd3164d8` (no local rebuild; Docker Hub metadata via build proxy timed out).

| Check | Result |
|---|---|
| `kubectl apply -k deploy/overlays/kind` | **OK** |
| `mock-llm` Ready | **1/1** |
| `ai-gateway` Ready | **1/1** (HPA removed; scaled to 1 for single-node Kind) |
| `agent` Ready | **1/1** (scaled to 1) |
| `/readyz` gateway + agent | **OK** |

Transcript: [`kind-apply/`](kind-apply/).
