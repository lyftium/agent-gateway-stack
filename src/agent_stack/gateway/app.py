"""OpenAI-compatible gateway in front of model servers (vLLM, KServe predictors).

Per request: authenticate the tenant, check the model is allowed, cap
max_tokens, apply quotas, then try the route's upstreams in order. Upstream 5xx
and connection errors fail over to the next upstream; upstream 4xx are returned
as-is. Logs and metrics carry tenant, model, upstream, status, latency and token
counts, never prompt or completion text.
"""

from __future__ import annotations

import codecs
import json
import os
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Histogram,
    generate_latest,
)

from agent_stack.common import get_logger, log_event, request_id, sha256_hex
from agent_stack.gateway.config import GatewayConfig, Route, Tenant, Upstream
from agent_stack.gateway.quota import Clock, Quotas

log = get_logger("gateway")

_LATENCY_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60)


class _Metrics:
    def __init__(self) -> None:
        self.registry = CollectorRegistry()
        self.requests = Counter(
            "gateway_requests",
            "Requests by outcome",
            ["tenant", "model", "status"],
            registry=self.registry,
        )
        self.latency = Histogram(
            "gateway_request_seconds",
            "Gateway end-to-end latency",
            ["model", "stream"],
            buckets=_LATENCY_BUCKETS,
            registry=self.registry,
        )
        self.ttft = Histogram(
            "gateway_time_to_first_token_seconds",
            "Streaming time to first token",
            ["model"],
            buckets=_LATENCY_BUCKETS,
            registry=self.registry,
        )
        self.tokens = Counter(
            "gateway_tokens",
            "Tokens reported by upstreams",
            ["tenant", "model", "kind"],
            registry=self.registry,
        )
        self.upstream_failures = Counter(
            "gateway_upstream_failures",
            "Upstream errors that triggered failover",
            ["upstream", "reason"],
            registry=self.registry,
        )
        self.quota_rejections = Counter(
            "gateway_quota_rejections",
            "Requests refused by quota",
            ["tenant"],
            registry=self.registry,
        )


def _error(status: int, kind: str, message: str, rid: str, **headers: str) -> JSONResponse:
    return JSONResponse(
        {"error": {"type": kind, "message": message}, "request_id": rid},
        status_code=status,
        headers={"x-request-id": rid, **headers},
    )


def _bearer(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    return token.strip() if scheme.lower() == "bearer" and token.strip() else None


def _served_by(rid: str, alias: str, upstream: str) -> dict[str, str]:
    """Responses keep the upstream's model name; these headers record the route taken."""
    return {"x-request-id": rid, "x-gateway-model": alias, "x-gateway-upstream": upstream}


def _parse_event(line: str) -> dict[str, Any]:
    try:
        event = json.loads(line[6:])
    except json.JSONDecodeError:
        return {}
    return event if isinstance(event, dict) else {}


def _has_content(event: dict[str, Any]) -> bool:
    return any((c.get("delta") or {}).get("content") for c in event.get("choices") or [])


def _upstream_headers(upstream: Upstream, rid: str) -> dict[str, str]:
    headers = {"content-type": "application/json", "x-request-id": rid}
    if upstream.api_key_env and (key := os.environ.get(upstream.api_key_env)):
        headers["authorization"] = f"Bearer {key}"
    return headers


def create_app(
    config: GatewayConfig,
    client: httpx.AsyncClient | None = None,
    clock: Clock = time.monotonic,
) -> FastAPI:
    http = client or httpx.AsyncClient()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        if client is None:
            await http.aclose()

    app = FastAPI(title="ai-gateway", docs_url=None, redoc_url=None, lifespan=lifespan)
    quotas = Quotas(clock)
    metrics = _Metrics()

    def authenticate(request: Request) -> Tenant | None:
        key = _bearer(request)
        return config.tenant_for_key_hash(sha256_hex(key)) if key else None

    def record(tenant: Tenant, alias: str, status: int, **fields: Any) -> None:
        metrics.requests.labels(tenant.name, alias, str(status)).inc()
        for kind in ("prompt_tokens", "completion_tokens"):
            if fields.get(kind):
                metrics.tokens.labels(tenant.name, alias, kind.split("_")[0]).inc(fields[kind])
        log_event(log, "request", tenant=tenant.name, model=alias, status=status, **fields)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz")
    async def readyz() -> dict[str, Any]:
        return {"status": "ready", "routes": [r.alias for r in config.routes]}

    @app.get("/metrics")
    async def prometheus() -> Response:
        return Response(generate_latest(metrics.registry), media_type=CONTENT_TYPE_LATEST)

    @app.get("/v1/models")
    async def models(request: Request) -> JSONResponse:
        rid = request_id(request.headers.get("x-request-id"))
        tenant = authenticate(request)
        if tenant is None:
            return _error(401, "authentication_error", "missing or unknown API key", rid)
        data = [{"id": alias, "object": "model", "owned_by": "gateway"} for alias in tenant.models]
        return JSONResponse({"object": "list", "data": data}, headers={"x-request-id": rid})

    @app.post("/v1/chat/completions")
    async def chat_completions(request: Request) -> Response:
        started = clock()
        rid = request_id(request.headers.get("x-request-id"))
        tenant = authenticate(request)
        if tenant is None:
            return _error(401, "authentication_error", "missing or unknown API key", rid)
        try:
            body = await request.json()
        except json.JSONDecodeError:
            return _error(400, "invalid_request_error", "body is not valid JSON", rid)
        if not isinstance(body, dict) or not isinstance(body.get("messages"), list):
            return _error(400, "invalid_request_error", "messages must be a list", rid)

        alias = str(body.get("model", ""))
        route = config.route(alias)
        if route is None:
            return _error(404, "model_not_found", f"unknown model {alias!r}", rid)
        if alias not in tenant.models:
            record(tenant, alias, 403, request_id=rid)
            return _error(403, "permission_error", f"model {alias!r} not allowed", rid)

        requested = body.get("max_tokens")
        if not isinstance(requested, int) or requested <= 0 or requested > tenant.max_tokens:
            body["max_tokens"] = tenant.max_tokens

        wait = quotas.admit(tenant.name, tenant.requests_per_minute, tenant.tokens_per_minute)
        if wait > 0:
            metrics.quota_rejections.labels(tenant.name).inc()
            record(tenant, alias, 429, request_id=rid)
            return _error(
                429, "rate_limit_error", "quota exceeded", rid, **{"retry-after": f"{wait:.0f}"}
            )

        if body.get("stream"):
            body["stream_options"] = {"include_usage": True}
            return await _stream(tenant, route, body, rid, started)
        return await _complete(tenant, route, body, rid, started)

    async def _complete(
        tenant: Tenant, route: Route, body: dict[str, Any], rid: str, started: float
    ) -> Response:
        for upstream in route.upstreams:
            payload = {**body, "model": upstream.model}
            try:
                resp = await http.post(
                    f"{str(upstream.base_url).rstrip('/')}/chat/completions",
                    json=payload,
                    headers=_upstream_headers(upstream, rid),
                    timeout=upstream.timeout_s,
                )
            except httpx.HTTPError as exc:
                metrics.upstream_failures.labels(upstream.name, type(exc).__name__).inc()
                continue
            if resp.status_code >= 500:
                metrics.upstream_failures.labels(upstream.name, str(resp.status_code)).inc()
                continue

            try:
                usage = resp.json().get("usage") or {}
            except (json.JSONDecodeError, AttributeError):
                usage = {}
            _charge(tenant, usage)
            elapsed = clock() - started
            metrics.latency.labels(route.alias, "false").observe(elapsed)
            record(
                tenant,
                route.alias,
                resp.status_code,
                request_id=rid,
                upstream=upstream.name,
                stream=False,
                latency_ms=round(elapsed * 1000, 1),
                prompt_tokens=usage.get("prompt_tokens"),
                completion_tokens=usage.get("completion_tokens"),
            )
            return Response(
                resp.content,
                status_code=resp.status_code,
                media_type="application/json",
                headers=_served_by(rid, route.alias, upstream.name),
            )
        record(tenant, route.alias, 502, request_id=rid)
        return _error(502, "upstream_unavailable", "no upstream could serve the request", rid)

    async def _stream(
        tenant: Tenant, route: Route, body: dict[str, Any], rid: str, started: float
    ) -> Response:
        for upstream in route.upstreams:
            payload = {**body, "model": upstream.model}
            req = http.build_request(
                "POST",
                f"{str(upstream.base_url).rstrip('/')}/chat/completions",
                json=payload,
                headers=_upstream_headers(upstream, rid),
                timeout=upstream.timeout_s,
            )
            try:
                resp = await http.send(req, stream=True)
            except httpx.HTTPError as exc:
                metrics.upstream_failures.labels(upstream.name, type(exc).__name__).inc()
                continue
            if resp.status_code >= 500:
                await resp.aclose()
                metrics.upstream_failures.labels(upstream.name, str(resp.status_code)).inc()
                continue
            if resp.status_code >= 400:
                content = await resp.aread()
                await resp.aclose()
                record(
                    tenant, route.alias, resp.status_code, request_id=rid, upstream=upstream.name
                )
                return Response(
                    content,
                    status_code=resp.status_code,
                    media_type="application/json",
                    headers={"x-request-id": rid},
                )
            return StreamingResponse(
                _relay(resp, tenant, route.alias, upstream.name, rid, started),
                media_type="text/event-stream",
                headers=_served_by(rid, route.alias, upstream.name),
            )
        record(tenant, route.alias, 502, request_id=rid)
        return _error(502, "upstream_unavailable", "no upstream could serve the request", rid)

    async def _relay(
        resp: httpx.Response, tenant: Tenant, alias: str, upstream: str, rid: str, started: float
    ) -> AsyncIterator[bytes]:
        # Bytes are forwarded as received. Lines are only JSON-parsed when they can
        # carry the first token or the usage block, which keeps per-chunk cost low.
        usage: dict[str, Any] = {}
        first_token_at: float | None = None
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        pending = ""
        try:
            async for raw in resp.aiter_raw():
                pending += decoder.decode(raw)
                *lines, pending = pending.split("\n")
                for line in lines:
                    if not line.startswith("data: {"):
                        continue
                    if first_token_at is None and '"content"' in line:
                        if _has_content(_parse_event(line)):
                            first_token_at = clock()
                            metrics.ttft.labels(alias).observe(first_token_at - started)
                    if '"usage"' in line:
                        usage = _parse_event(line).get("usage") or usage
                yield raw
        finally:
            await resp.aclose()
            _charge(tenant, usage)
            elapsed = clock() - started
            metrics.latency.labels(alias, "true").observe(elapsed)
            record(
                tenant,
                alias,
                resp.status_code,
                request_id=rid,
                upstream=upstream,
                stream=True,
                latency_ms=round(elapsed * 1000, 1),
                ttft_ms=round((first_token_at - started) * 1000, 1) if first_token_at else None,
                prompt_tokens=usage.get("prompt_tokens"),
                completion_tokens=usage.get("completion_tokens"),
            )

    def _charge(tenant: Tenant, usage: dict[str, Any]) -> None:
        used = int(usage.get("total_tokens") or 0)
        if used:
            quotas.charge_tokens(
                tenant.name, tenant.requests_per_minute, tenant.tokens_per_minute, used
            )

    return app
