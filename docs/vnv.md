# Verification vs validation (agent tools)

| Kind | Question | What we run |
|---|---|---|
| **Verification** | Did we build the tool right? | Analytical ISA baselines (`docs/physics-validation.md`), unit conversions against known factors, pydantic schema rejects, allowlist misses |
| **Validation** | Is it fit for a real engineering workflow? | **Not claimed** for flight/programme use. Laptop mock-model runs only; OpenShift manifests prepared, not applied |

## Domain refusal (verification)

- `isa_atmosphere` rejects altitudes outside `[-500, 20000]` m (tropopause model scope).
- `convert_units` refuses cross-quantity conversions.
- Side-effect tools never execute without `POST /v1/agent/approvals` (approve-once).

OOD / programme validation against wind-tunnel or fleet data is out of scope for this
public demonstrator — say so in interviews rather than implying fitness.
