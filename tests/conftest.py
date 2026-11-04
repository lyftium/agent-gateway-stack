from __future__ import annotations

import httpx
import pytest

from agent_stack.common import sha256_hex
from agent_stack.gateway.app import create_app as create_gateway
from agent_stack.gateway.config import GatewayConfig
from agent_stack.mockllm.app import create_app as create_mock

AGENT_KEY = "test-agent-key"
TEAM_KEY = "test-team-key"


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class HostRouter(httpx.AsyncBaseTransport):
    """Sends each request to the ASGI app registered for its host.

    Host "down" raises a connection error; host "broken" answers 503.
    """

    def __init__(self, apps: dict[str, object]) -> None:
        self._transports = {h: httpx.ASGITransport(app=a) for h, a in apps.items()}
        self.seen: list[str] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        host = request.url.host
        self.seen.append(host)
        if host == "down":
            raise httpx.ConnectError("connection refused", request=request)
        if host == "broken":
            return httpx.Response(503, json={"error": "overloaded"})
        return await self._transports[host].handle_async_request(request)


def make_config(
    upstream_hosts: list[str], rpm: int = 60, tpm: int = 100_000, max_tokens: int = 256
) -> GatewayConfig:
    return GatewayConfig.model_validate(
        {
            "routes": [
                {
                    "alias": "chat",
                    "upstreams": [
                        {"name": host, "base_url": f"http://{host}/v1", "model": "served-model"}
                        for host in upstream_hosts
                    ],
                },
                {
                    "alias": "restricted",
                    "upstreams": [{"name": "mock", "base_url": "http://mock/v1", "model": "other"}],
                },
            ],
            "tenants": [
                {
                    "name": "agent",
                    "key_sha256": sha256_hex(AGENT_KEY),
                    "models": ["chat"],
                    "requests_per_minute": rpm,
                    "tokens_per_minute": tpm,
                    "max_tokens": max_tokens,
                },
                {
                    "name": "team",
                    "key_sha256": sha256_hex(TEAM_KEY),
                    "models": ["chat", "restricted"],
                    "requests_per_minute": 1000,
                    "tokens_per_minute": 1_000_000,
                    "max_tokens": 1024,
                },
            ],
        }
    )


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def mock_app():
    return create_mock()


def gateway_client(
    config: GatewayConfig, mock_app, clock=None
) -> tuple[httpx.AsyncClient, HostRouter]:
    router = HostRouter({"mock": mock_app})
    upstream = httpx.AsyncClient(transport=router)
    kwargs = {"clock": clock} if clock else {}
    app = create_gateway(config, client=upstream, **kwargs)
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://gateway"
    ), router


def auth(key: str = AGENT_KEY) -> dict[str, str]:
    return {"authorization": f"Bearer {key}"}
