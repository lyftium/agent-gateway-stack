"""Latency the gateway adds, measured against the mock model on one machine.

Starts the mock model and the gateway as separate uvicorn processes (one
worker each), then sends the same requests directly to the model and through
the gateway at several concurrency levels. The mock answers instantly, so the
difference is gateway cost: auth, quota, usage accounting, one extra local hop.

    python bench/gateway_overhead.py --requests 2000 --out results/gateway-overhead.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import platform
import statistics
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
MOCK_PORT, GATEWAY_PORT = 18081, 18082
KEY = "dev-agent-key"
BODY = {
    "model": "chat",
    "max_tokens": 32,
    "messages": [{"role": "user", "content": "Summarise the inspection notes in one line."}],
}


def _start(service: str, port: int, env: dict[str, str]) -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, "-m", "agent_stack", service, "--host", "127.0.0.1", "--port", str(port)],
        env={**os.environ, "PYTHONPATH": str(ROOT / "src"), **env},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )


def _wait_ready(url: str, timeout_s: float = 20) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            if httpx.get(url, timeout=1).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.1)
    raise RuntimeError(f"{url} not ready after {timeout_s}s")


def _percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(q * (len(ordered) - 1))))]


async def _load(url: str, headers: dict, body: dict, n: int, concurrency: int) -> dict:
    latencies: list[float] = []
    errors = 0
    limits = httpx.Limits(max_connections=concurrency, max_keepalive_connections=concurrency)
    async with httpx.AsyncClient(limits=limits, timeout=30) as client:
        queue: asyncio.Queue[int] = asyncio.Queue()
        for i in range(n):
            queue.put_nowait(i)

        async def worker() -> None:
            nonlocal errors
            while not queue.empty():
                queue.get_nowait()
                started = time.perf_counter()
                resp = await client.post(url, json=body, headers=headers)
                if body.get("stream"):
                    await resp.aread()
                latencies.append((time.perf_counter() - started) * 1000)
                if resp.status_code != 200:
                    errors += 1

        for _ in range(min(50, n)):
            await client.post(url, json=body, headers=headers)
        wall = time.perf_counter()
        await asyncio.gather(*(worker() for _ in range(concurrency)))
        wall = time.perf_counter() - wall
    return {
        "requests": n,
        "errors": errors,
        "throughput_rps": round(n / wall, 1),
        "p50_ms": round(statistics.median(latencies), 3),
        "p95_ms": round(_percentile(latencies, 0.95), 3),
        "p99_ms": round(_percentile(latencies, 0.99), 3),
    }


def _median_run(runs: list[dict]) -> dict:
    keys = ("throughput_rps", "p50_ms", "p95_ms", "p99_ms")
    out = {k: round(statistics.median(r[k] for r in runs), 3) for k in keys}
    out["errors"] = sum(r["errors"] for r in runs)
    out["p50_ms_per_repeat"] = [r["p50_ms"] for r in runs]
    return out


async def run(n: int, levels: list[int], repeats: int) -> list[dict]:
    """Direct and gateway runs alternate within each repeat so drift on the
    machine affects both sides; each figure is the median over repeats."""
    rows = []
    direct = f"http://127.0.0.1:{MOCK_PORT}/v1/chat/completions"
    gateway = f"http://127.0.0.1:{GATEWAY_PORT}/v1/chat/completions"
    auth = {"authorization": f"Bearer {KEY}"}
    for stream in (False, True):
        body = {**BODY, "stream": stream}
        for c in levels:
            direct_runs, gateway_runs = [], []
            for _ in range(repeats):
                direct_runs.append(await _load(direct, {}, body, n, c))
                gateway_runs.append(await _load(gateway, auth, body, n, c))
            d, g = _median_run(direct_runs), _median_run(gateway_runs)
            rows.append(
                {
                    "stream": stream,
                    "concurrency": c,
                    "direct": d,
                    "via_gateway": g,
                    "added_p50_ms": round(g["p50_ms"] - d["p50_ms"], 3),
                    "added_p95_ms": round(g["p95_ms"] - d["p95_ms"], 3),
                }
            )
            print(
                f"stream={stream!s:5} c={c:3}  direct p50 {d['p50_ms']:7.2f} ms "
                f"{d['throughput_rps']:7.1f} rps | gateway p50 {g['p50_ms']:7.2f} ms "
                f"{g['throughput_rps']:7.1f} rps | +{rows[-1]['added_p50_ms']:.2f} ms",
                flush=True,
            )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--requests", type=int, default=2000)
    parser.add_argument("--concurrency", default="1,8,32")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--out", type=Path, default=ROOT / "results" / "gateway-overhead.json")
    args = parser.parse_args()
    levels = [int(c) for c in args.concurrency.split(",")]

    procs = [
        _start("mockllm", MOCK_PORT, {}),
        _start("gateway", GATEWAY_PORT, {"GATEWAY_CONFIG": str(ROOT / "config/bench.yaml")}),
    ]
    try:
        _wait_ready(f"http://127.0.0.1:{MOCK_PORT}/health")
        _wait_ready(f"http://127.0.0.1:{GATEWAY_PORT}/readyz")
        rows = asyncio.run(run(args.requests, levels, args.repeats))
    finally:
        for p in procs:
            p.terminate()
            p.wait(timeout=10)

    result = {
        "what": "latency added by the gateway in front of an instant mock model",
        "setup": {
            "python": platform.python_version(),
            "machine": platform.machine(),
            "system": platform.system(),
            "cpu_count": os.cpu_count(),
            "uvicorn_workers": 1,
            "uvloop": False,
            "httptools": False,
            "client": "httpx, same machine, keep-alive",
            "requests_per_point": args.requests,
            "repeats": args.repeats,
        },
        "results": rows,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
