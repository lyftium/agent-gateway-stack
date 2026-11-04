# Image digests (GHCR)

**Status.** Digests are recorded only after a successful `docker build` + `docker push` to `ghcr.io/lyftium/...`.

| Image | Tag | Digest | Built from | Date (UTC) |
|---|---|---|---|---|
| `ghcr.io/lyftium/agent-gateway-stack` | _(pending)_ | _(not pushed)_ | `Dockerfile` @ main | — |
| `ghcr.io/lyftium/agent-gateway-stack` | _(pending)_ | _(not pushed)_ | `Dockerfile` @ main | — |

## How to fill

```bash
# after docker login ghcr.io
docker build -t ghcr.io/lyftium/agent-gateway-stack:dev .
DIGEST=$(docker inspect --format='{{index .RepoDigests 0}}' ghcr.io/lyftium/agent-gateway-stack:dev | cut -d@ -f2)
docker push ghcr.io/lyftium/agent-gateway-stack:dev
# record DIGEST in this table — never invent
```

Until a row has a real `sha256:…`, treat image references in manifests as **prepared**, not released artefacts.
