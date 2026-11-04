"""Gateway configuration: model routes and tenants, loaded from YAML.

API keys never appear in the file. Tenants are identified by the SHA-256 of
their key, so the ConfigMap can be read by anyone without leaking credentials.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field, HttpUrl, field_validator, model_validator


class Upstream(BaseModel):
    name: str
    base_url: HttpUrl
    model: str = Field(description="Model name the upstream server expects")
    api_key_env: str | None = Field(
        default=None, description="Env var holding the upstream key, if it needs one"
    )
    timeout_s: float = Field(default=60.0, gt=0, le=600)


class Route(BaseModel):
    alias: str = Field(pattern=r"^[A-Za-z0-9._-]{1,64}$")
    upstreams: list[Upstream] = Field(min_length=1, description="Tried in order")


class Tenant(BaseModel):
    name: str = Field(pattern=r"^[a-z0-9-]{1,40}$")
    key_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    models: list[str] = Field(min_length=1)
    requests_per_minute: int = Field(gt=0)
    tokens_per_minute: int = Field(gt=0)
    max_tokens: int = Field(gt=0, description="Cap applied to each request's max_tokens")


class GatewayConfig(BaseModel):
    routes: list[Route] = Field(min_length=1)
    tenants: list[Tenant] = Field(min_length=1)

    @field_validator("routes")
    @classmethod
    def _unique_aliases(cls, routes: list[Route]) -> list[Route]:
        aliases = [r.alias for r in routes]
        if len(aliases) != len(set(aliases)):
            raise ValueError("route aliases must be unique")
        return routes

    @model_validator(mode="after")
    def _tenants_reference_known_routes(self) -> GatewayConfig:
        known = {r.alias for r in self.routes}
        for tenant in self.tenants:
            if missing := set(tenant.models) - known:
                raise ValueError(
                    f"tenant {tenant.name} references unknown models {sorted(missing)}"
                )
        if len({t.key_sha256 for t in self.tenants}) != len(self.tenants):
            raise ValueError("two tenants share the same key")
        return self

    def route(self, alias: str) -> Route | None:
        return next((r for r in self.routes if r.alias == alias), None)

    def tenant_for_key_hash(self, key_sha256: str) -> Tenant | None:
        return next((t for t in self.tenants if t.key_sha256 == key_sha256), None)


def load_config(path: str | Path) -> GatewayConfig:
    return GatewayConfig.model_validate(yaml.safe_load(Path(path).read_text()))
