from __future__ import annotations

import json

import httpx
import pytest
from conftest import TEAM_KEY, auth, gateway_client, make_config

pytestmark = pytest.mark.anyio

CHAT = {"model": "chat", "messages": [{"role": "user", "content": "hello there"}]}


async def test_rejects_missing_and_unknown_keys(mock_app):
    client, _ = gateway_client(make_config(["mock"]), mock_app)
    assert (await client.post("/v1/chat/completions", json=CHAT)).status_code == 401
    resp = await client.post("/v1/chat/completions", json=CHAT, headers=auth("nope"))
    assert resp.status_code == 401
    assert resp.json()["error"]["type"] == "authentication_error"


async def test_tenant_can_only_use_its_models(mock_app):
    client, _ = gateway_client(make_config(["mock"]), mock_app)
    body = {**CHAT, "model": "restricted"}
    assert (await client.post("/v1/chat/completions", json=body, headers=auth())).status_code == 403
    assert (
        await client.post("/v1/chat/completions", json=body, headers=auth(TEAM_KEY))
    ).status_code == 200
    unknown = await client.post(
        "/v1/chat/completions", json={**CHAT, "model": "gpt-x"}, headers=auth()
    )
    assert unknown.status_code == 404


async def test_models_lists_only_allowed_aliases(mock_app):
    client, _ = gateway_client(make_config(["mock"]), mock_app)
    resp = await client.get("/v1/models", headers=auth())
    assert [m["id"] for m in resp.json()["data"]] == ["chat"]


async def test_rewrites_model_and_caps_max_tokens(mock_app):
    captured = {}

    async def spy(request):
        captured.update(json.loads(request.content))
        return await original(request)

    client, router = gateway_client(make_config(["mock"], max_tokens=64), mock_app)
    original = router._transports["mock"].handle_async_request
    router._transports["mock"].handle_async_request = spy
    resp = await client.post(
        "/v1/chat/completions", json={**CHAT, "max_tokens": 5000}, headers=auth()
    )
    assert resp.status_code == 200
    assert captured["model"] == "served-model"
    assert captured["max_tokens"] == 64
    assert resp.json()["model"] == "served-model"
    assert resp.headers["x-gateway-model"] == "chat"
    assert resp.headers["x-gateway-upstream"] == "mock"


async def test_fails_over_on_connect_error_and_5xx(mock_app):
    client, router = gateway_client(make_config(["down", "broken", "mock"]), mock_app)
    resp = await client.post("/v1/chat/completions", json=CHAT, headers=auth())
    assert resp.status_code == 200
    assert resp.headers["x-gateway-upstream"] == "mock"
    assert router.seen == ["down", "broken", "mock"]
    metrics = (await client.get("/metrics")).text
    assert 'gateway_upstream_failures_total{reason="ConnectError",upstream="down"} 1.0' in metrics
    assert 'gateway_upstream_failures_total{reason="503",upstream="broken"} 1.0' in metrics


async def test_returns_502_when_every_upstream_fails(mock_app):
    client, _ = gateway_client(make_config(["down", "broken"]), mock_app)
    resp = await client.post("/v1/chat/completions", json=CHAT, headers=auth())
    assert resp.status_code == 502
    assert resp.json()["error"]["type"] == "upstream_unavailable"


async def test_request_quota_returns_429_then_recovers(mock_app, clock):
    client, _ = gateway_client(make_config(["mock"], rpm=2), mock_app, clock)
    for _ in range(2):
        assert (
            await client.post("/v1/chat/completions", json=CHAT, headers=auth())
        ).status_code == 200
    limited = await client.post("/v1/chat/completions", json=CHAT, headers=auth())
    assert limited.status_code == 429
    assert int(limited.headers["retry-after"]) == 30
    clock.now += 30
    assert (await client.post("/v1/chat/completions", json=CHAT, headers=auth())).status_code == 200


async def test_token_quota_charges_reported_usage(mock_app, clock):
    client, _ = gateway_client(make_config(["mock"], tpm=6), mock_app, clock)
    first = await client.post("/v1/chat/completions", json=CHAT, headers=auth())
    assert first.json()["usage"]["total_tokens"] >= 6
    assert (await client.post("/v1/chat/completions", json=CHAT, headers=auth())).status_code == 429


async def test_streaming_passthrough_counts_usage_and_ttft(mock_app):
    client, _ = gateway_client(make_config(["mock"]), mock_app)
    resp = await client.post("/v1/chat/completions", json={**CHAT, "stream": True}, headers=auth())
    assert resp.status_code == 200
    events = [line[6:] for line in resp.text.splitlines() if line.startswith("data: ")]
    assert events[-1] == "[DONE]"
    chunks = [json.loads(e) for e in events[:-1]]
    text = "".join(c["choices"][0]["delta"].get("content", "") for c in chunks if c["choices"])
    assert text.startswith("Mock answer to: hello there")
    assert all(c["model"] == "served-model" for c in chunks)
    assert chunks[-1]["usage"]["total_tokens"] > 0
    metrics = (await client.get("/metrics")).text
    assert 'gateway_time_to_first_token_seconds_count{model="chat"} 1.0' in metrics
    assert 'gateway_tokens_total{kind="completion",model="chat",tenant="agent"}' in metrics


class _Chunked(httpx.AsyncByteStream):
    def __init__(self, data: bytes, size: int) -> None:
        self._parts = [data[i : i + size] for i in range(0, len(data), size)]

    async def __aiter__(self):
        for part in self._parts:
            yield part


async def test_stream_events_split_across_chunks_are_still_parsed(mock_app, capsys):
    events = [
        {"choices": [{"index": 0, "delta": {"content": "Température "}}]},
        {"choices": [{"index": 0, "delta": {"content": "216.65 K"}}]},
        {"choices": [], "usage": {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10}},
    ]
    sse = "".join(f"data: {json.dumps(e, ensure_ascii=False)}\n\n" for e in events)
    data = (sse + "data: [DONE]\n\n").encode()

    async def chunked_upstream(request):
        return httpx.Response(
            200, stream=_Chunked(data, size=7), headers={"content-type": "text/event-stream"}
        )

    client, router = gateway_client(make_config(["mock"]), mock_app)
    router._transports["mock"].handle_async_request = chunked_upstream
    resp = await client.post("/v1/chat/completions", json={**CHAT, "stream": True}, headers=auth())
    assert resp.content == data
    log_line = [ln for ln in capsys.readouterr().out.splitlines() if '"stream": true' in ln][0]
    assert json.loads(log_line)["completion_tokens"] == 3
    assert json.loads(log_line)["ttft_ms"] is not None


async def test_logs_never_contain_message_content(mock_app, capsys):
    client, _ = gateway_client(make_config(["mock"]), mock_app)
    secret = "propriety-drawing-PN-4471"
    body = {"model": "chat", "messages": [{"role": "user", "content": secret}]}
    await client.post("/v1/chat/completions", json=body, headers=auth())
    await client.post("/v1/chat/completions", json={**body, "stream": True}, headers=auth())
    out = capsys.readouterr().out
    assert out.count('"event": "request"') == 2
    assert secret not in out


async def test_request_id_is_propagated_or_replaced(mock_app):
    client, _ = gateway_client(make_config(["mock"]), mock_app)
    ok = await client.post(
        "/v1/chat/completions", json=CHAT, headers={**auth(), "x-request-id": "abc-123"}
    )
    assert ok.headers["x-request-id"] == "abc-123"
    unsafe = await client.post(
        "/v1/chat/completions", json=CHAT, headers={**auth(), "x-request-id": "bad id\nforged"}
    )
    assert unsafe.headers["x-request-id"] != "bad id\nforged"
    assert len(unsafe.headers["x-request-id"]) == 32


async def test_rejects_malformed_bodies(mock_app):
    client, _ = gateway_client(make_config(["mock"]), mock_app)
    resp = await client.post(
        "/v1/chat/completions",
        content=b"{not json",
        headers={**auth(), "content-type": "application/json"},
    )
    assert resp.status_code == 400
    resp = await client.post("/v1/chat/completions", json={"model": "chat"}, headers=auth())
    assert resp.status_code == 400
