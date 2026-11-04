from __future__ import annotations

import json

import httpx
import pytest
from conftest import AGENT_KEY, HostRouter, make_config

from agent_stack.agent.app import create_app as create_agent
from agent_stack.agent.loop import run_agent
from agent_stack.agent.tools import TOOLS
from agent_stack.gateway.app import create_app as create_gateway

pytestmark = pytest.mark.anyio


def stack(mock_app, rpm: int = 60, key: str = AGENT_KEY) -> httpx.AsyncClient:
    """Agent -> gateway -> mock model, all in-process."""
    gateway = create_gateway(
        make_config(["mock"], rpm=rpm),
        client=httpx.AsyncClient(transport=HostRouter({"mock": mock_app})),
    )
    agent = create_agent(
        gateway_url="http://gateway/v1",
        api_key=key,
        model="chat",
        client=httpx.AsyncClient(transport=HostRouter({"gateway": gateway})),
    )
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=agent), base_url="http://agent")


def scripted(*replies: dict):
    """An LLM that returns canned assistant messages in order."""
    calls = []

    async def llm(messages, tools):
        calls.append(messages)
        return {
            "choices": [{"message": replies[len(calls) - 1]}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        }

    llm.calls = calls
    return llm


def tool_call(name: str, arguments: str) -> dict:
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {"id": "c1", "type": "function", "function": {"name": name, "arguments": arguments}}
        ],
    }


async def test_end_to_end_run_through_gateway(mock_app):
    client = stack(mock_app)
    resp = await client.post(
        "/v1/agent/runs", json={"task": "Air density at 11000 m in the ISA model?"}
    )
    body = resp.json()
    assert resp.status_code == 200, body
    assert body["status"] == "completed"
    assert body["model_calls"] == 2
    [step] = body["steps"]
    assert step["tool"] == "isa_atmosphere" and step["outcome"] == "ok"
    assert step["result"]["density_kg_m3"] == pytest.approx(0.36392, rel=5e-4)
    record = body["record"]
    assert record["model"] == "chat" and len(record["prompt_version"]) == 12
    assert record["tool_versions"]["isa_atmosphere"] == "1.0"


async def test_side_effecting_tool_stops_for_approval(mock_app):
    client = stack(mock_app)
    resp = await client.post("/v1/agent/runs", json={"task": "Submit a cfd run with 2000000 cells"})
    body = resp.json()
    assert body["status"] == "awaiting_approval"
    assert body["pending_call"]["tool"] == "submit_simulation_job"
    assert body["pending_call"]["arguments"]["mesh_cells"] == 2_000_000
    assert body["steps"][-1]["outcome"] == "approval_required"


async def test_gateway_quota_is_surfaced_to_caller(mock_app):
    client = stack(mock_app, rpm=1)
    resp = await client.post("/v1/agent/runs", json={"task": "density at 1000 m"})
    assert resp.status_code == 429
    assert resp.json()["error"]["type"] == "gateway_error"


async def test_bad_agent_key_is_reported_as_401(mock_app):
    resp = await stack(mock_app, key="wrong").post("/v1/agent/runs", json={"task": "hi"})
    assert resp.status_code == 401


async def test_invalid_arguments_are_fed_back_to_the_model():
    llm = scripted(
        tool_call("isa_atmosphere", '{"altitude_m": 99999}'),
        {"role": "assistant", "content": "Altitude is out of range."},
    )
    run = await run_agent("density at 99 km", llm, TOOLS)
    assert run.status == "completed"
    assert run.steps[0].outcome == "error"
    tool_msg = llm.calls[1][-1]
    assert tool_msg["role"] == "tool" and "invalid arguments" in tool_msg["content"]


async def test_unknown_tool_and_bad_json_do_not_crash():
    llm = scripted(
        tool_call("rm_rf", "{}"),
        tool_call("convert_units", "{not json"),
        {"role": "assistant", "content": "done"},
    )
    run = await run_agent("x", llm, TOOLS)
    assert [s.outcome for s in run.steps] == ["error", "error"]
    assert "unknown tool" in json.loads(run.steps[0].error)["error"]


async def test_tool_errors_are_returned_not_raised():
    llm = scripted(
        tool_call("convert_units", '{"value": 1, "from_unit": "m", "to_unit": "psi"}'),
        {"role": "assistant", "content": "cannot"},
    )
    run = await run_agent("x", llm, TOOLS)
    assert "cannot convert" in run.steps[0].error


async def test_loop_stops_at_max_steps():
    call = tool_call("isa_atmosphere", '{"altitude_m": 0}')
    run = await run_agent("loop forever", scripted(call, call, call), TOOLS, max_steps=3)
    assert run.status == "max_steps"
    assert run.model_calls == 3 and len(run.steps) == 3


async def test_agent_logs_omit_task_text(mock_app, capsys):
    secret = "confidential-part-PN-998 at 3000 m"
    await stack(mock_app).post("/v1/agent/runs", json={"task": secret})
    out = capsys.readouterr().out
    assert '"event": "run"' in out
    assert "confidential-part" not in out


async def test_rejects_empty_task(mock_app):
    resp = await stack(mock_app).post("/v1/agent/runs", json={"task": ""})
    assert resp.status_code == 422
