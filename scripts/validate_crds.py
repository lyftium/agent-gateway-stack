"""Validate rendered manifests against CRD schemas, strictly.

kubeconform has no schema for OpenShift Routes and only loose ones for KServe,
so this script reads the CRDs' openAPIV3Schema directly and rejects unknown
fields wherever the CRD declares its properties (the same rule the API server
applies with field validation set to Strict).

    kubectl kustomize deploy/overlays/openshift-ai > /tmp/r.yaml
    python scripts/validate_crds.py /tmp/r.yaml .cache/crds/*.yaml
"""

from __future__ import annotations

import copy
import sys
from typing import Any

import jsonschema
import yaml


def _strict(schema: Any) -> Any:
    if isinstance(schema, dict):
        for key in [k for k, v in schema.items() if v is None]:
            del schema[key]
        if (
            "properties" in schema
            and not schema.get("x-kubernetes-preserve-unknown-fields")
            and "additionalProperties" not in schema
        ):
            schema["additionalProperties"] = False
        for value in schema.values():
            _strict(value)
    elif isinstance(schema, list):
        for value in schema:
            _strict(value)
    return schema


def load_schemas(paths: list[str]) -> dict[tuple[str, str], dict]:
    schemas = {}
    for path in paths:
        with open(path) as fh:
            crd = yaml.safe_load(fh)
        group, kind = crd["spec"]["group"], crd["spec"]["names"]["kind"]
        for version in crd["spec"]["versions"]:
            schema = _strict(copy.deepcopy(version["schema"]["openAPIV3Schema"]))
            schema.setdefault("properties", {})["metadata"] = {"type": "object"}
            schemas[(kind, f"{group}/{version['name']}")] = schema
    return schemas


def main(rendered: str, crds: list[str]) -> int:
    schemas = load_schemas(crds)
    failures = checked = 0
    with open(rendered) as fh:
        docs = [d for d in yaml.safe_load_all(fh) if d]
    for doc in docs:
        key = (doc["kind"], doc["apiVersion"])
        if key not in schemas:
            continue
        checked += 1
        errors = list(jsonschema.Draft7Validator(schemas[key]).iter_errors(doc))
        print(f"{doc['kind']}/{doc['metadata']['name']}: {'valid' if not errors else 'INVALID'}")
        for err in errors[:10]:
            failures += 1
            print(f"    {'.'.join(map(str, err.path))}: {err.message[:200]}")
    print(f"{checked} custom resources checked, {failures} errors")
    return 1 if failures or not checked else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2:]))
