# Gateway overhead benchmark

**Question.** How much latency does the gateway add to a request, and where does
it stop scaling?

**Method.** `bench/gateway_overhead.py` starts the mock model and the gateway as
two uvicorn processes (one worker each, no uvloop/httptools) on one machine. The
mock answers instantly, so the measured difference is gateway cost: auth, quota,
usage accounting, one extra local HTTP hop. For each concurrency level it sends
1 500 requests directly to the mock, then 1 500 through the gateway, and repeats
that pair three times; figures are medians over the three repeats. Client:
httpx with keep-alive, same machine. Hardware: Apple M1 Pro (10 cores), Python 3.11.3.

Raw results: [`results/gateway-overhead.json`](../results/gateway-overhead.json)
(current code) and
[`results/gateway-overhead-before-relay-fix.json`](../results/gateway-overhead-before-relay-fix.json)
(previous streaming relay, same method).

## Results (current code)

| Mode | Concurrency | Direct p50 | Gateway p50 | Added p50 | Gateway req/s | Errors |
|---|---:|---:|---:|---:|---:|---:|
| non-stream | 1 | 1.03 ms | 2.67 ms | **+1.65 ms** | 333 | 0 |
| non-stream | 8 | 7.40 ms | 13.32 ms | +5.92 ms | 500 | 0 |
| non-stream | 32 | 59.4 ms | 117.1 ms | +57.7 ms | 201 | 0 |
| stream | 1 | 1.55 ms | 3.09 ms | **+1.54 ms** | 299 | 0 |
| stream | 8 | 7.50 ms | 15.28 ms | +7.78 ms | 401 | 0 |
| stream | 32 | 72.8 ms | 115.9 ms | +43.1 ms | 157 | 0 |

## Streaming relay, before and after

The first relay parsed every SSE event as JSON and re-serialised it to replace
the model name. The current one forwards upstream bytes unchanged and parses only
lines that can carry the first token or the usage block.

| Concurrency | Added p50, before | Added p50, after | Gateway req/s, before | after |
|---:|---:|---:|---:|---:|
| 1 | +1.70 ms | +1.54 ms | 253 | 299 |
| 8 | +16.1 ms | +7.78 ms | 206 | 401 |
| 32 | +35.2 ms | +43.1 ms | 176 | 157 |

## Reading the numbers

- **At low concurrency the gateway costs about 1.5–1.7 ms.** A vLLM request on a
  small model takes tens of milliseconds to first token and hundreds to
  seconds end to end, so this is a few percent at most.
- **The relay fix matters at moderate load:** at 8 concurrent streams it halves
  the added latency and doubles throughput.
- **At 32 concurrent requests one worker is saturated** (≈150–200 req/s for this
  Python stack on this laptop) and latency is queueing. The before/after
  difference at 32 is within run-to-run spread (gateway p50 per repeat: 105–127 ms
  after, 81–113 ms before). The answer here is more replicas (the base manifests
  run 2, HPA up to 6), not more micro-optimisation.
- **Where the remaining time goes** (cProfile, concurrency 1): gateway Python
  code is about 0.4 ms per request; most of the rest is the extra HTTP hop through
  httpx and pure-Python HTTP parsing. On the same machine an aiohttp client
  completed the same upstream call in 1.1 ms versus 2.3 ms for httpx, and
  `uvicorn[standard]` (uvloop + httptools) is the usual production setting. Both are
  measured candidates, not applied.

## Limits

- One machine, so client, gateway and mock compete for the same CPU. Absolute
  throughput is not transferable to a cluster; the relative overhead is the result.
- Single runs varied by up to 2× at concurrency 32 (laptop background load), which
  is why the script interleaves and repeats. Treat the concurrency-32 rows as
  "saturated", not as precise figures.
- The mock returns short completions. Long generations make the gateway's
  share of total latency smaller, not larger.
