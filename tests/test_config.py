from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from agent_stack.gateway.config import GatewayConfig, load_config

ROOT = Path(__file__).resolve().parents[1]


def _base() -> dict:
    return {
        "routes": [
            {"alias": "chat", "upstreams": [{"name": "a", "base_url": "http://a/v1", "model": "m"}]}
        ],
        "tenants": [
            {
                "name": "t",
                "key_sha256": "0" * 64,
                "models": ["chat"],
                "requests_per_minute": 1,
                "tokens_per_minute": 1,
                "max_tokens": 1,
            }
        ],
    }


def test_rejects_tenant_with_unknown_model():
    cfg = _base()
    cfg["tenants"][0]["models"] = ["chat", "missing"]
    with pytest.raises(ValidationError, match="unknown models"):
        GatewayConfig.model_validate(cfg)


def test_rejects_duplicate_aliases_and_keys():
    cfg = _base()
    cfg["routes"].append(cfg["routes"][0])
    with pytest.raises(ValidationError, match="unique"):
        GatewayConfig.model_validate(cfg)
    cfg = _base()
    cfg["tenants"].append({**cfg["tenants"][0], "name": "u"})
    with pytest.raises(ValidationError, match="same key"):
        GatewayConfig.model_validate(cfg)


def test_rejects_plaintext_key():
    cfg = _base()
    cfg["tenants"][0]["key_sha256"] = "my-api-key"
    with pytest.raises(ValidationError):
        GatewayConfig.model_validate(cfg)


SHIPPED = sorted((ROOT / "config").glob("*.yaml")) + sorted(
    (ROOT / "deploy" / "overlays").rglob("gateway.yaml")
)


def test_configs_are_shipped():
    assert len(SHIPPED) >= 3


@pytest.mark.parametrize("path", SHIPPED, ids=lambda p: str(p.relative_to(ROOT)))
def test_shipped_configs_are_valid(path: Path):
    load_config(path)
