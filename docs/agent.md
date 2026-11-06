# Agent service

A tool-calling agent deployed as its own microservice. It has one dependency,
the gateway, and one credential, its gateway API key. It never talks to a model
server directly, so the gateway's auth, quotas and logging policy apply to it
like to any other tenant.

## Loop

```mermaid
sequenceDiagram
    participant C as Caller
    participant A as Agent
    participant G as Gateway
    participant M as Model (vLLM)
    C->>A: POST /v1/agent/runs {task}
    loop at most max_steps model calls
        A->>G: chat/completions + tool schemas
        G->>M: (auth, quota, route)
        M-->>A: tool_calls or final answer
        alt tool call
            A->>A: registry lookup → JSON parse → pydantic validation
            alt requires approval
                A-->>C: status=awaiting_approval, pending_call
            else
                A->>A: run with timeout
                A->>G: tool result (or error) as a tool message
            end
        end
    end
    A-->>C: status, answer, steps, usage, record
```

The model proposes; code decides. Each step is checked in this order, and a
failure at any point becomes a tool message the model can react to, never an
exception that ends the run:

1. **Known tool?** Unknown names return the list of available tools.
2. **Parsable arguments?** Invalid JSON is reported with the parser's message.
3. **Valid arguments?** Each tool has a pydantic model (ranges, enums, lengths).
   `isa_atmosphere(altitude_m=99999)` is rejected with the field and the limit.
4. **Side effects?** Tools marked `requires_approval` are validated but not run.
   The run stops with `status: awaiting_approval` and the exact proposed call.
5. **Run with a timeout** in a worker thread, so a slow tool cannot block the loop.

The loop ends on a final answer, on an approval stop, or after `max_steps`
(default 6, capped at 10 per request), which bounds cost when a model keeps calling tools.

## Tools

| Tool | What it computes | Checked against |
|---|---|---|
| `isa_atmosphere` | T, p, ρ, speed of sound, 0–20 km | ICAO standard atmosphere tables at 0, 5, 11 and 15 km (`tests/test_tools.py`) |
| `convert_units` | length, pressure, force, mass, temperature | exact definitions (ft = 0.3048 m, lbf, psi); refuses cross-quantity conversions |
| `tolerance_stackup` | 1-D stack, worst case and RSS | hand-computed example |
| `submit_simulation_job` | (side effect) queue a CFD/FEA job | never executed by the agent; approval only |

Calculations are deterministic and done in code, not by the model. The
system prompt tells the model to use tools for every number; the tests check
that tool results, not model text, carry the values.

## Run record

Every response includes a `record`:

```json
{
  "run_id": "…", "request_id": "…", "started_at": "2026-…Z", "duration_ms": 41.3,
  "service_version": "0.1.0", "git_sha": "…", "prompt_version": "a1b2c3d4e5f6",
  "model": "chat", "tool_versions": {"isa_atmosphere": "1.0", "…": "…"}
}
```

together with every step (tool, arguments, outcome, result or error, duration)
and token usage. With the gateway's `x-gateway-upstream` header and log line
under the same request id, a run can be traced to the code version, the prompt
version, the concrete model that answered and each tool call it made.

## What is not here

- Persisting run records (they are returned and logged; a store is deployment-specific).
- Independent operator authentication on the approval endpoint, real queue execution, or resuming a paused run. The demo records an accepted intent; the caller re-submits after review.
- Evaluation of a real model's tool-calling accuracy. The mock model is a test
  double: it proves the plumbing, not the model's judgement.
