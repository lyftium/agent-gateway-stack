"""Entry point: `python -m agent_stack {gateway,agent,mockllm}`, configured by env vars."""

from __future__ import annotations

import argparse
import os
import sys

import uvicorn
from fastapi import FastAPI

from agent_stack.agent.app import create_app as create_agent
from agent_stack.gateway.app import create_app as create_gateway
from agent_stack.gateway.config import load_config
from agent_stack.mockllm.app import create_app as create_mock


def _require(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        sys.exit(f"missing required environment variable {name}")
    return value


def build(service: str) -> FastAPI:
    if service == "gateway":
        return create_gateway(load_config(_require("GATEWAY_CONFIG")))
    if service == "agent":
        return create_agent(
            gateway_url=_require("AGENT_GATEWAY_URL"),
            api_key=_require("AGENT_API_KEY"),
            model=os.environ.get("AGENT_MODEL", "chat"),
        )
    if service == "mockllm":
        return create_mock(
            ttft_s=float(os.environ.get("MOCK_TTFT_MS", "0")) / 1000,
            token_delay_s=float(os.environ.get("MOCK_TOKEN_DELAY_MS", "0")) / 1000,
        )
    raise ValueError(f"unknown service {service!r}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="agent-stack")
    parser.add_argument("service", choices=["gateway", "agent", "mockllm"])
    parser.add_argument("--host", default=os.environ.get("HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8080")))
    args = parser.parse_args()
    uvicorn.run(
        build(args.service), host=args.host, port=args.port, log_level="warning", access_log=False
    )


if __name__ == "__main__":
    main()
