"""Closed tool allowlist + approve-once idempotency for side effects."""

from __future__ import annotations

import json

import pytest

from agent_stack.agent.approval import ApprovalLedger, approval_fingerprint, execute_approved
from agent_stack.agent.loop import run_agent
from agent_stack.agent.tools import ALLOWED_TOOL_NAMES, TOOLS, submit_simulation_job


def test_registry_matches_closed_allowlist():
    assert set(TOOLS) == ALLOWED_TOOL_NAMES
    assert "bash" not in ALLOWED_TOOL_NAMES
    assert "submit_simulation_job" in ALLOWED_TOOL_NAMES


def test_schemas_only_advertise_allowlisted_names():
    names = {t.schema()["function"]["name"] for t in TOOLS.values()}
    assert names == ALLOWED_TOOL_NAMES


def test_side_effect_fn_refuses_direct_call():
    from agent_stack.agent.tools import SubmitJobArgs

    with pytest.raises(RuntimeError, match="human approval"):
        submit_simulation_job(
            SubmitJobArgs(case_name="direct", solver="cfd", mesh_cells=100)
        )


@pytest.mark.anyio
async def test_unknown_tool_is_allowlist_miss_not_execution():
    calls = []

    async def llm(messages, tools):
        calls.append(1)
        if len(calls) == 1:
            return {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "x",
                                    "type": "function",
                                    "function": {
                                        "name": "rm_rf",
                                        "arguments": "{}",
                                    },
                                }
                            ],
                        }
                    }
                ],
                "usage": {},
            }
        return {
            "choices": [{"message": {"role": "assistant", "content": "done"}}],
            "usage": {},
        }

    run = await run_agent("delete everything", llm, TOOLS)
    assert run.steps[0].outcome == "error"
    assert "unknown tool" in json.loads(run.steps[0].error)["error"]


def test_execute_approved_is_idempotent():
    ledger = ApprovalLedger()
    args = {"case_name": "wing-box", "solver": "fea", "mesh_cells": 5000}
    first = execute_approved("submit_simulation_job", args, ledger)
    second = execute_approved("submit_simulation_job", args, ledger)
    assert first["status"] == "accepted"
    assert second["status"] == "duplicate"
    assert first["idempotency_key"] == second["idempotency_key"]
    assert first["idempotency_key"] == approval_fingerprint(
        "submit_simulation_job", args, TOOLS["submit_simulation_job"].version
    )


def test_execute_approved_rejects_non_approval_tools():
    out = execute_approved("isa_atmosphere", {"altitude_m": 0}, ApprovalLedger())
    assert out["status"] == "rejected"
