# Physics tool validation (ISA atmosphere)

**Status.** Demonstrator validation note for the agent tools that wrap International Standard Atmosphere helpers. Not a CFD claim.

## Intent

When an agent exposes a physics or engineering calculator, treat it like any other tool: schema-bound inputs, domain checks, and a reference solver for regression — not “the LLM remembers the formula.”

## Reference

- ISA: ICAO Doc 7488 / standard troposphere–stratosphere piecewise model (implementation in this repo’s tools).
- Analytical baselines: closed-form temperature, pressure, density vs geometric altitude in the documented validity bands.

## Proposed checks (run in CI)

1. **Point tests** at textbook altitudes (e.g. 0 m, 11 km tropopause) against published tables within a tight absolute/relative tolerance.
2. **Domain gates**: reject or flag altitudes outside the coded model; never silently extrapolate.
3. **Units**: SI only at the API boundary; convert explicitly inside the tool.
4. **Agent path**: LLM may *call* the tool; answers that invent numbers without a tool result fail the eval harness.

## What this does not prove

- Compressible CFD, engine performance decks, or proprietary Safran models.
- That tool use alone makes an agent safe for operational decisions — keep HITL for consequential actions (`docs/` gateway policies).
