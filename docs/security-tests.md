# Security / agent-boundary tests (public proof map)

**Status.** Maps pack-style agent threats to **existing** pytest in this repo. Not a penetration test or AI Act claim.

| Threat theme | What we assert | Where |
|---|---|---|
| Auth fail-closed | Bad API key → 401 | `tests/test_gateway.py`, `tests/test_agent.py` |
| Team / model ACL | Forbidden model / team → 403 | `tests/test_gateway.py` |
| Quotas | RPM / token budgets → 429 then recover | `tests/test_gateway.py`, agent surfaces gateway 429 |
| No prompt logging | Secret-like content never appears in gateway logs | `tests/test_gateway.py` (`test_*secret*` / no-prompt-log) |
| Side-effect tools | `requires_approval` tools stop the run (`awaiting_approval`) | `tests/test_agent.py` |
| Unknown / malformed tools | Unknown name or bad JSON → error steps, no crash | `tests/test_agent.py` |
| Schema / domain gates | OOD ISA altitude rejected; unit mismatch refused | `tests/test_tools.py` |
| Tool output as data | Invalid args fed back to the model as tool errors, not elevated privileges | `tests/test_agent.py` |
| Prompt-injection posture | Injected `bash` / privileged tool names → unknown-tool error; side-effect tools still `awaiting_approval` | `tests/test_prompt_injection_posture.py` |

## Prompt injection posture (engineering)

- Treat documents and tool outputs as **untrusted data**, not as authorisation.
- The agent loop never executes arbitrary shell or network tools from this catalogue.
- Side effects require human approval before execution.
- Adding a new tool = new typed schema + tests for reject paths + approval flag review.

## Verify

```bash
pip install -e '.[dev]'
pytest tests/test_gateway.py tests/test_agent.py tests/test_tools.py tests/test_prompt_injection_posture.py -q
```

## Limits

- Laptop + mock LLM; not a live OpenShift security assessment.
- No claim that these tests exhaust prompt-injection catalogues.
- NetworkPolicy / SCC belong to cluster apply evidence (see drawing-review-service manifests).

Related: `docs/physics-validation.md` (ISA analytical baselines in `tests/test_tools.py`).
