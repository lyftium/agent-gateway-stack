"""Deterministic stand-in for an OpenAI-compatible model server.

It is a test double, not a model: tool selection is keyword rules, so the
gateway and agent can be tested and benchmarked on a CPU. `ttft_s` and
`token_delay_s` emulate prefill and decode time.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

_NUMBER = r"(-?\d+(?:\.\d+)?)"


def _plan_tool_call(text: str, tools: set[str]) -> tuple[str, dict[str, Any]] | None:
    lowered = text.lower()
    if "submit" in lowered and "submit_simulation_job" in tools:
        cells = re.search(r"(\d+)\s*cells", lowered)
        return "submit_simulation_job", {
            "case_name": "wing-section",
            "solver": "cfd" if "cfd" in lowered else "fea",
            "mesh_cells": int(cells.group(1)) if cells else 100000,
        }
    if (m := re.search(_NUMBER + r"\s*(m|ft)\b", lowered)) and "isa_atmosphere" in tools:
        value, unit = float(m.group(1)), m.group(2)
        return "isa_atmosphere", {"altitude_m": value * 0.3048 if unit == "ft" else value}
    if (m := re.search(r"convert\s+" + _NUMBER + r"\s*(\w+)\s+to\s+(\w+)", lowered)) and (
        "convert_units" in tools
    ):
        return "convert_units", {
            "value": float(m.group(1)),
            "from_unit": m.group(2),
            "to_unit": m.group(3),
        }
    pairs = re.findall(_NUMBER + r"\s*(?:±|\+/-)\s*" + _NUMBER, text)
    if pairs and "tolerance_stackup" in tools:
        return "tolerance_stackup", {
            "dimensions": [{"nominal": float(n), "tolerance": float(t)} for n, t in pairs]
        }
    return None


def _usage(messages: list[dict[str, Any]], completion: str) -> dict[str, int]:
    prompt = sum(len(str(m.get("content") or "").split()) for m in messages)
    out = len(completion.split())
    return {"prompt_tokens": prompt, "completion_tokens": out, "total_tokens": prompt + out}


def _reply(messages: list[dict[str, Any]], tools: set[str]) -> dict[str, Any]:
    last = messages[-1]
    if last.get("role") == "tool":
        return {"role": "assistant", "content": f"Computed result: {last.get('content')}"}
    if tools and (call := _plan_tool_call(str(last.get("content", "")), tools)):
        name, args = call
        return {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": f"call_{uuid.uuid4().hex[:12]}",
                    "type": "function",
                    "function": {"name": name, "arguments": json.dumps(args)},
                }
            ],
        }
    words = str(last.get("content", "")).split()[:12]
    return {"role": "assistant", "content": "Mock answer to: " + " ".join(words)}


def create_app(ttft_s: float = 0.0, token_delay_s: float = 0.0) -> FastAPI:
    app = FastAPI(title="mock-llm", docs_url=None, redoc_url=None)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/v1/models")
    async def models() -> dict[str, Any]:
        return {"object": "list", "data": [{"id": "mock", "object": "model"}]}

    @app.post("/v1/chat/completions")
    async def chat(request: Request) -> Any:
        body = await request.json()
        messages = body.get("messages") or [{"role": "user", "content": ""}]
        tools = {t["function"]["name"] for t in body.get("tools") or []}
        message = _reply(messages, tools)
        usage = _usage(messages, message.get("content") or "")
        base = {
            "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
            "created": int(time.time()),
            "model": body.get("model", "mock"),
        }
        if not body.get("stream"):
            await asyncio.sleep(ttft_s + token_delay_s * usage["completion_tokens"])
            finish = "tool_calls" if message.get("tool_calls") else "stop"
            return JSONResponse(
                {
                    **base,
                    "object": "chat.completion",
                    "usage": usage,
                    "choices": [{"index": 0, "message": message, "finish_reason": finish}],
                }
            )
        include_usage = bool((body.get("stream_options") or {}).get("include_usage"))
        return StreamingResponse(
            _stream(base, message, usage, include_usage, ttft_s, token_delay_s),
            media_type="text/event-stream",
        )

    return app


async def _stream(
    base: dict[str, Any],
    message: dict[str, Any],
    usage: dict[str, int],
    include_usage: bool,
    ttft_s: float,
    token_delay_s: float,
) -> AsyncIterator[bytes]:
    def event(payload: dict[str, Any]) -> bytes:
        chunk = {**base, "object": "chat.completion.chunk", **payload}
        return f"data: {json.dumps(chunk)}\n\n".encode()

    await asyncio.sleep(ttft_s)
    if message.get("tool_calls"):
        yield event(
            {
                "choices": [
                    {
                        "index": 0,
                        "delta": {"role": "assistant", "tool_calls": message["tool_calls"]},
                    }
                ]
            }
        )
    else:
        for i, word in enumerate((message.get("content") or "").split()):
            if i:
                await asyncio.sleep(token_delay_s)
            delta = {"content": (" " if i else "") + word}
            yield event({"choices": [{"index": 0, "delta": delta}]})
    yield event({"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]})
    if include_usage:
        yield event({"choices": [], "usage": usage})
    yield b"data: [DONE]\n\n"
