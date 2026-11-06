# Agent-gateway performance benchmark

The measured latency benchmark is documented in [`docs/benchmark.md`](docs/benchmark.md), with its implementation in [`bench/gateway_overhead.py`](bench/gateway_overhead.py) and raw results in [`results/gateway-overhead.json`](results/gateway-overhead.json). This summary is an index to those artifacts; it adds no new performance result.

## Method

The mock model answers immediately, so the difference between direct and gateway requests measures gateway cost rather than model generation. The gateway and mock run as separate single-worker uvicorn processes on the same machine. At each concurrency level, 1,500 direct and 1,500 gateway requests are interleaved and repeated three times; reported figures are medians. Streaming is measured separately.

Recorded environment: Apple M1 Pro (10 cores), Python 3.11.3, httpx keep-alive, no uvloop or httptools. Other conditions and limitations are in the detailed report.

## Exact reproduction command

```bash
python bench/gateway_overhead.py --requests 1500 --concurrency 1,8,32 --repeats 3   --out results/gateway-overhead.json
```

The script starts local services using the checked-in development configuration. Inspect it before running. Only an existing raw result is published here; the server benchmark was not re-run for this publication.

## Current-code measurements

| Mode | Concurrency | Added p50 (ms) | Gateway req/s | Errors |
|---|---:|---:|---:|---:|
| Non-stream | 1 | 1.65 | 333 | 0 |
| Non-stream | 8 | 5.92 | 500 | 0 |
| Non-stream | 32 | 57.7 | 201 | 0 |
| Stream | 1 | 1.54 | 299 | 0 |
| Stream | 8 | 7.78 | 401 | 0 |
| Stream | 32 | 43.1 | 157 | 0 |

See `docs/benchmark.md` for direct/gateway percentiles and the previous-relay comparison.

## Limits

An instant mock, one laptop, shared client/server CPU, and queueing at high concurrency. Absolute values do not transfer to a cluster or real model serving. Unit and integration tests verify behavior; they are not performance benchmarks.
