"""Agent microservice. It reaches models only through the gateway, so the
gateway's auth, quotas and logging policy apply to agent traffic too.

Each run returns a record (code version, prompt version, model alias, tool
versions, every tool call and its outcome) that can be stored as an audit trail.
Logs carry counts, tool names and outcomes, not the task text.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Histogram,
    generate_latest,
)
from pydantic import BaseModel, Field

from agent_stack import __version__
from agent_stack.agent.approval import ApprovalLedger, execute_approved
from agent_stack.agent.loop import PROMPT_VERSION, run_agent
from agent_stack.agent.tools import TOOLS
from agent_stack.common import get_logger, git_sha, log_event, request_id

log = get_logger("agent")


class RunRequest(BaseModel):
    task: str = Field(min_length=1, max_length=4000)
    max_steps: int = Field(default=6, ge=1, le=10)


class ApproveRequest(BaseModel):
    """Human-reviewed side-effect call (from awaiting_approval.pending_call)."""

    tool: str = Field(min_length=1, max_length=64)
    arguments: dict[str, Any]
    approved_by: str = Field(
        min_length=1, max_length=64, description="operator id / email local part"
    )


class GatewayError(Exception):
    def __init__(self, status: int, body: Any) -> None:
        super().__init__(f"gateway returned {status}")
        self.status, self.body = status, body


def create_app(
    gateway_url: str,
    api_key: str,
    model: str,
    client: httpx.AsyncClient | None = None,
    llm_timeout_s: float = 60.0,
) -> FastAPI:
    http = client or httpx.AsyncClient()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        if client is None:
            await http.aclose()

    app = FastAPI(title="agent", docs_url=None, redoc_url=None, lifespan=lifespan)
    ledger = ApprovalLedger()
    registry = CollectorRegistry()
    runs = Counter("agent_runs", "Agent runs by final status", ["status"], registry=registry)
    tool_calls = Counter(
        "agent_tool_calls", "Tool calls by outcome", ["tool", "outcome"], registry=registry
    )
    approvals = Counter(
        "agent_approvals", "Approved side effects by status", ["status"], registry=registry
    )
    duration = Histogram(
        "agent_run_seconds",
        "Agent run duration",
        registry=registry,
        buckets=(0.01, 0.05, 0.1, 0.5, 1, 2.5, 5, 10, 30, 60, 120),
    )

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz")
    async def readyz() -> dict[str, Any]:
        return {"status": "ready", "model": model, "tools": sorted(TOOLS)}

    @app.get("/metrics")
    async def prometheus() -> Response:
        return Response(generate_latest(registry), media_type=CONTENT_TYPE_LATEST)

    @app.post("/v1/agent/runs")
    async def create_run(body: RunRequest, request: Request) -> JSONResponse:
        rid = request_id(request.headers.get("x-request-id"))
        run_id = uuid.uuid4().hex
        started_at = datetime.now(UTC).isoformat()
        started = time.perf_counter()

        async def llm(messages: list[dict], tools: list[dict]) -> dict:
            resp = await http.post(
                f"{gateway_url.rstrip('/')}/chat/completions",
                json={
                    "model": model,
                    "messages": messages,
                    "tools": tools,
                    "tool_choice": "auto",
                    "temperature": 0,
                },
                headers={"authorization": f"Bearer {api_key}", "x-request-id": rid},
                timeout=llm_timeout_s,
            )
            if resp.status_code != 200:
                try:
                    detail = resp.json()
                except ValueError:
                    detail = resp.text[:200]
                raise GatewayError(resp.status_code, detail)
            return resp.json()

        try:
            result = await run_agent(body.task, llm, TOOLS, max_steps=body.max_steps)
        except GatewayError as exc:
            status = exc.status if exc.status in (401, 403, 429) else 502
            runs.labels("gateway_error").inc()
            log_event(
                log,
                "run",
                run_id=run_id,
                request_id=rid,
                status="gateway_error",
                gateway_status=exc.status,
            )
            return JSONResponse(
                {
                    "error": {"type": "gateway_error", "upstream": exc.body},
                    "run_id": run_id,
                    "request_id": rid,
                },
                status_code=status,
                headers={"x-request-id": rid},
            )
        except httpx.HTTPError as exc:
            runs.labels("gateway_unreachable").inc()
            log_event(
                log,
                "run",
                run_id=run_id,
                request_id=rid,
                status="gateway_unreachable",
                error=type(exc).__name__,
            )
            return JSONResponse(
                {"error": {"type": "gateway_unreachable"}, "run_id": run_id, "request_id": rid},
                status_code=502,
                headers={"x-request-id": rid},
            )

        elapsed = time.perf_counter() - started
        duration.observe(elapsed)
        runs.labels(result.status).inc()
        for step in result.steps:
            tool_calls.labels(step.tool if step.tool in TOOLS else "unknown", step.outcome).inc()
        log_event(
            log,
            "run",
            run_id=run_id,
            request_id=rid,
            status=result.status,
            model_calls=result.model_calls,
            tools=[f"{s.tool}:{s.outcome}" for s in result.steps],
            duration_ms=round(elapsed * 1000, 1),
            **result.usage,
        )
        record = {
            "run_id": run_id,
            "request_id": rid,
            "started_at": started_at,
            "duration_ms": round(elapsed * 1000, 1),
            "service_version": __version__,
            "git_sha": git_sha(),
            "prompt_version": PROMPT_VERSION,
            "model": model,
            "tool_versions": {name: t.version for name, t in TOOLS.items()},
        }
        return JSONResponse({**result.to_dict(), "record": record}, headers={"x-request-id": rid})

    @app.post("/v1/agent/approvals")
    async def approve_side_effect(body: ApproveRequest, request: Request) -> JSONResponse:
        """Accept a human-reviewed tool call at most once per fingerprint."""
        rid = request_id(request.headers.get("x-request-id"))
        out = execute_approved(body.tool, body.arguments, ledger)
        approvals.labels(out["status"]).inc()
        log_event(
            log,
            "approval",
            request_id=rid,
            approved_by=body.approved_by,
            tool=body.tool,
            status=out["status"],
            idempotency_key=out.get("idempotency_key"),
        )
        code = 200 if out["status"] in ("accepted", "duplicate") else 400
        return JSONResponse(
            {**out, "request_id": rid},
            status_code=code,
            headers={"x-request-id": rid},
        )

    return app
