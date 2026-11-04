"""Bounded tool-calling loop.

The model proposes; this code decides. Every tool call is checked against the
registry, its arguments are parsed and validated, it runs with a timeout, and
the outcome (including errors) goes back to the model as a tool message. The
loop ends on a final answer, on a call that needs human approval, or after
`max_steps` model calls.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from pydantic import ValidationError

from agent_stack.agent.tools import Tool
from agent_stack.common import sha256_hex

SYSTEM_PROMPT = (
    "You are an engineering assistant. Use the provided tools for any calculation; "
    "do not compute numbers yourself. If a tool returns an error, correct the arguments "
    "or explain why the task cannot be done. Answer concisely and state units."
)
PROMPT_VERSION = sha256_hex(SYSTEM_PROMPT)[:12]

LLMCall = Callable[[list[dict[str, Any]], list[dict[str, Any]]], Awaitable[dict[str, Any]]]
Status = Literal["completed", "awaiting_approval", "max_steps"]


@dataclass
class Step:
    index: int
    tool: str
    arguments: dict[str, Any] | None
    outcome: Literal["ok", "error", "approval_required"]
    result: dict[str, Any] | None = None
    error: str | None = None
    duration_ms: float = 0.0


@dataclass
class RunResult:
    status: Status
    answer: str | None
    steps: list[Step] = field(default_factory=list)
    model_calls: int = 0
    usage: dict[str, int] = field(
        default_factory=lambda: {"prompt_tokens": 0, "completion_tokens": 0}
    )
    pending_call: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


async def _execute(tool: Tool, raw_args: str, timeout_s: float) -> tuple[dict, dict | None]:
    """Returns (tool message payload, parsed arguments). Raises nothing."""
    try:
        parsed = json.loads(raw_args or "{}")
    except json.JSONDecodeError as exc:
        return {"error": f"arguments are not valid JSON: {exc.msg}"}, None
    try:
        args = tool.args.model_validate(parsed)
    except ValidationError as exc:
        errors = [{"loc": e["loc"], "msg": e["msg"]} for e in exc.errors()]
        return {"error": "invalid arguments", "details": errors}, parsed
    try:
        result = await asyncio.wait_for(asyncio.to_thread(tool.fn, args), timeout_s)
    except TimeoutError:
        return {"error": f"tool timed out after {timeout_s}s"}, parsed
    except (ValueError, ArithmeticError) as exc:
        return {"error": str(exc)}, parsed
    return {"result": result}, parsed


async def run_agent(
    task: str,
    llm: LLMCall,
    tools: dict[str, Tool],
    max_steps: int = 6,
    tool_timeout_s: float = 5.0,
) -> RunResult:
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": task},
    ]
    schemas = [t.schema() for t in tools.values()]
    run = RunResult(status="max_steps", answer=None)

    for _ in range(max_steps):
        response = await llm(messages, schemas)
        run.model_calls += 1
        for key in run.usage:
            run.usage[key] += int((response.get("usage") or {}).get(key) or 0)
        message = response["choices"][0]["message"]
        calls = message.get("tool_calls") or []
        if not calls:
            run.status, run.answer = "completed", message.get("content") or ""
            return run

        messages.append(
            {"role": "assistant", "content": message.get("content"), "tool_calls": calls}
        )
        for call in calls:
            name = call["function"]["name"]
            raw_args = call["function"].get("arguments", "{}")
            started = time.perf_counter()
            step = Step(index=len(run.steps), tool=name, arguments=None, outcome="error")
            tool = tools.get(name)
            if tool is None:
                payload = {"error": f"unknown tool {name!r}; available: {sorted(tools)}"}
            elif tool.requires_approval:
                payload, step.arguments = await _validate_only(tool, raw_args)
                if "error" not in payload:
                    step.outcome = "approval_required"
                    run.steps.append(step)
                    run.status = "awaiting_approval"
                    run.pending_call = {
                        "tool": name,
                        "arguments": step.arguments,
                        "tool_version": tool.version,
                    }
                    return run
            else:
                payload, step.arguments = await _execute(tool, raw_args, tool_timeout_s)
                if "result" in payload:
                    step.outcome, step.result = "ok", payload["result"]
            if step.outcome == "error":
                step.error = json.dumps(payload)
            step.duration_ms = round((time.perf_counter() - started) * 1000, 2)
            run.steps.append(step)
            messages.append(
                {"role": "tool", "tool_call_id": call.get("id", ""), "content": json.dumps(payload)}
            )
    return run


async def _validate_only(tool: Tool, raw_args: str) -> tuple[dict, dict | None]:
    try:
        parsed = json.loads(raw_args or "{}")
        tool.args.model_validate(parsed)
    except json.JSONDecodeError as exc:
        return {"error": f"arguments are not valid JSON: {exc.msg}"}, None
    except ValidationError as exc:
        return {
            "error": "invalid arguments",
            "details": [{"loc": e["loc"], "msg": e["msg"]} for e in exc.errors()],
        }, None
    return {}, parsed
