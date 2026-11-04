# Physics tool validation (ISA atmosphere)

**Status.** Demonstrator validation for International Standard Atmosphere helpers. Not a CFD claim.

## Intent

When an agent exposes a physics or engineering calculator, treat it like any other tool: schema-bound inputs, domain checks, and a reference solver for regression — not “the LLM remembers the formula.”

## Reference

- ISA: ICAO Doc 7488 / ISO 2533 piecewise troposphere–stratopause model (implementation in `src/agent_stack/agent/tools.py`).
- Analytical baselines: closed-form temperature, pressure, density vs geopotential altitude in the coded bands.

## Automated checks (CI / local)

`tests/test_tools.py` already asserts:

1. **Point tests** at 0 m, 5 km, 11 km, 15 km against ISA table values (temperature, pressure, density tolerances).
2. **Speed of sound** at sea level ≈ 340.29 m/s.
3. **Domain gates**: altitudes outside `[-500, 20000]` m rejected via pydantic (`ValidationError`).
4. **Units**: SI-oriented conversions with refuse-on-mismatch for incompatible quantities.
5. **Agent path**: end-to-end run asks density at 11 km and must match the tool result (`tests/test_agent.py`).

```bash
pytest tests/test_tools.py tests/test_agent.py -q
```

## What this does not prove

- Compressible CFD, engine decks, or proprietary programme models.
- That tool use alone makes an agent safe for operational decisions — keep HITL for consequential actions (`docs/security-tests.md`).
