# Demo path (screener / interview)

No company names. Use only what this repository proves.

## 90 seconds

1. Problem: every client reimplements keys, quotas, routing; agents add opaque tool loops.
2. Show top README table (Verify / Status / GHCR digest).
3. Point at evidence: CI badge, [`docs/evidence/kind-apply/`](docs/evidence/kind-apply/) (Ready + agent-run ISA + approve-once).
4. State limits: mock-llm Kind; OpenShift AI manifests prepared, not live-applied; no real-model tool accuracy claim.

## 10 minutes (laptop)

```bash
python -m pytest -q                 # allowlist + approve-once + ISA + injection
make validate                       # kubeconform overlays + CRD checks
# optional if Kind + GHCR image available:
# kubectl apply -k deploy/overlays/kind
# kubectl -n agent-stack port-forward pod/$(kubectl -n agent-stack get pod -l app.kubernetes.io/name=agent -o jsonpath='{.items[0].metadata.name}') 18080:8080
# curl -s localhost:18080/v1/agent/runs -H 'content-type: application/json' \
#   -d '{"task":"Air density at 11000 m in the ISA model?"}'
# curl -s localhost:18080/v1/agent/runs -H 'content-type: application/json' \
#   -d '{"task":"Submit a simulation job named kind-demo-job"}'
# # then POST /v1/agent/approvals with pending_call (+ second POST → duplicate)
```

Talk track while commands run:

| Minute | Show | Say |
|---|---|---|
| 0–2 | Architecture mermaid | Gateway owns auth/quotas; agent owns bounded tool loop |
| 2–4 | `pytest` allowlist + approve-once | Model proposes; service decides; side effects stop |
| 4–6 | Kind Ready + agent-run transcript | ISA completed; submit_simulation_job → awaiting_approval → accepted → duplicate |
| 6–8 | Trust boundaries + `docs/vnv.md` | Injection posture + ISA physics refuse keep demo claims bounded |
| 8–9 | GHCR digest + OpenShift overlay | Image published; Route/KServe prepared, not live |
| 9–10 | Limits + next | Real-model tool accuracy; shared multi-replica quotas |

## Do not claim

- Live OpenShift AI / customer cluster apply
- Tool-calling accuracy with a production LLM (mock proves plumbing)
- That Kind Ready equals production multi-tenant hardening
