# Evidence

Recorded local results for this demonstrator. Quote only what these files contain.

| File | What it records | Boundary |
|---|---|---|
| [`laptop-smoke-2026-11-04.md`](laptop-smoke-2026-11-04.md) | Local CPU test / Compose path notes | Mock LLM only |
| [`kind-smoke-2026-11-04.md`](kind-smoke-2026-11-04.md) | Kind apply, Ready pods, agent ISA run, approve-once | Local Kind; mock backend; no real-model tool quality |
| [`kind-apply/`](kind-apply/) | Transcripts behind the Kind smoke summary | Includes deploy and agent-run logs |

Public CI: [`.github/workflows/ci.yml`](../../.github/workflows/ci.yml). Image digests: [`docs/image-digests.md`](../image-digests.md).

Do not invent timings, digests, or tool-calling accuracy. Approval here records an intent; it is not an independent operator auth system.
