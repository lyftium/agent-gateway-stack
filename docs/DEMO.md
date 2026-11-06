# Interview demo — gateway & agent

Walkthrough for a screener. Stick to artefacts in this repo.

## 90 seconds

1. **Question:** how do you stop every client reinventing keys, quotas, and opaque tool loops?
2. Open the README “Start here” block.
3. Point at CI and [`docs/evidence/kind-apply/`](evidence/kind-apply/) (Ready + ISA + approve-once).
4. **Limits out loud:** Kind against mock-llm; OpenShift AI manifests prepared, not live; no real-model tool-accuracy claim.

## 10 minutes

```bash
python -m pytest -q
make validate
# optional if Kind + image available — see README Deploy section
```

| Minute | Show | Say |
|---|---|---|
| 0–2 | Architecture diagram | Gateway owns auth/quotas; agent owns the bounded tool loop |
| 2–4 | `pytest` allowlist + approve-once | Model proposes; service decides; side effects stop |
| 4–6 | Kind agent-run transcript | ISA completed; submit job → awaiting_approval → accepted → duplicate |
| 6–8 | `docs/vnv.md` | Injection posture + ISA refuse keep claims bounded |
| 8–9 | GHCR digest + OpenShift overlay | Image published; Route/KServe prepared, not live |
| 9–10 | Limits | Real-model tool accuracy and shared multi-replica quotas still open |

## Do not claim

- Live OpenShift AI / customer cluster apply
- Tool-calling accuracy with a real model
- Shared quotas across replicas (today they are per replica)
