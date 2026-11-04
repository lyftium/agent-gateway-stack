"""Human-approved side effects with idempotency keys.

The agent loop never executes `requires_approval` tools. After a human reviews
`pending_call`, the caller invokes `execute_approved` once. A second submit with
the same fingerprint returns `duplicate` instead of re-queuing.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from agent_stack.agent.tools import TOOLS, Tool
from agent_stack.common import sha256_hex


def approval_fingerprint(tool_name: str, arguments: dict[str, Any], tool_version: str) -> str:
    blob = json.dumps(
        {"tool": tool_name, "arguments": arguments, "tool_version": tool_version},
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256_hex(blob)


@dataclass
class ApprovalLedger:
    """In-memory accept-once ledger (swap for Redis/DB in a real deployment)."""

    _accepted: set[str] = field(default_factory=set)

    def seen(self, key: str) -> bool:
        return key in self._accepted

    def claim(self, key: str) -> bool:
        """Return True if this is the first claim; False if already accepted."""
        if key in self._accepted:
            return False
        self._accepted.add(key)
        return True


def execute_approved(
    tool_name: str,
    arguments: dict[str, Any],
    ledger: ApprovalLedger,
    *,
    tools: dict[str, Tool] | None = None,
) -> dict[str, Any]:
    """Run a previously reviewed side-effect tool at most once per fingerprint.

    Does **not** call tools that raise on direct invoke; records an accepted
    queue intent. Unknown / non-approval tools are rejected.
    """
    registry = tools if tools is not None else TOOLS
    tool = registry.get(tool_name)
    if tool is None:
        return {"status": "rejected", "error": f"unknown tool {tool_name!r}"}
    if not tool.requires_approval:
        return {
            "status": "rejected",
            "error": f"{tool_name!r} does not require approval; call it via the agent loop",
        }
    try:
        validated = tool.args.model_validate(arguments).model_dump()
    except Exception as exc:  # noqa: BLE001 — surface validation to caller
        return {"status": "rejected", "error": f"invalid arguments: {exc}"}

    key = approval_fingerprint(tool_name, validated, tool.version)
    if not ledger.claim(key):
        return {
            "status": "duplicate",
            "idempotency_key": key,
            "tool": tool_name,
            "arguments": validated,
        }
    # Demonstrator: accept the job record without talking to a real queue.
    return {
        "status": "accepted",
        "idempotency_key": key,
        "tool": tool_name,
        "tool_version": tool.version,
        "arguments": validated,
        "job_id": f"job-{key[:12]}",
    }
