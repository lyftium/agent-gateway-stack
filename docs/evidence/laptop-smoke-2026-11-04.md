# Laptop smoke — agent-gateway-stack — 2026-11-04

Environment: local macOS, Python 3.11, mock upstream (no live vLLM).

| Check | Result |
|---|---|
| `pip install -e '.[dev]' && pytest -q` | **48 passed** (gateway, agent, tools, ISA physics, prompt-injection posture) |
| `make validate` | CRD / manifest schema checks (see Makefile) |
| `docker compose up --build` | **Blocked** here — Docker Hub DNS refused |
| OpenShift AI / KServe apply | Manifests schema-validated; **not applied** to a live cluster |

## Security / physics pointers

- Injection posture tests: `tests/test_prompt_injection_posture.py` — notes in `docs/security-tests.md`
- ISA analytical baselines: `docs/physics-validation.md` + ISA cases in `tests/test_tools.py`

When Docker Hub is reachable: compose smoke, then paste image digests into `docs/image-digests.md`.
