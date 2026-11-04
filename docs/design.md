# Gateway design

The gateway sits between every caller (people, scripts, the agent service) and
the model servers. It owns the concerns that should not be re-implemented in
each client: who may call which model, how much, through which backend, and
what gets recorded.

## Request path

```
client ──► auth ──► model allowed? ──► cap max_tokens ──► quota ──► upstream 1 ─┐
           401        404 / 403                              429      5xx/conn  │
                                                                      error ──► upstream 2 ─► … ─► 502
```

| Step | Behaviour | Why |
|---|---|---|
| Auth | `Authorization: Bearer <key>`; the gateway stores only `sha256(key)` per tenant | the config can live in a ConfigMap and be reviewed without exposing keys |
| Model access | tenants list the route aliases they may use; unknown alias → 404, not allowed → 403 | clients name a stable alias (`chat`), not a server; the model behind it can change |
| `max_tokens` | missing or above the tenant cap → set to the cap | bounds the cost of a single request before it reaches the GPU |
| Quotas | token buckets per tenant: requests/min, and tokens/min charged from the upstream's `usage` | request limits alone don't bound GPU time; token limits do |
| Routing | each alias has an ordered list of upstreams; connection errors and 5xx fail over, 4xx are returned unchanged | a 4xx is the caller's problem and retrying it elsewhere just repeats it |
| Streaming | SSE bytes are forwarded as received; `stream_options.include_usage` is set so the last event carries token counts | the gateway must not add latency per token, and must still account for usage |
| Response | body is the upstream's, unchanged; `x-gateway-model`, `x-gateway-upstream`, `x-request-id` headers record the route taken | the concrete model that answered is part of the audit trail |

## Logging policy

One JSON line per request: request id, tenant, alias, upstream, status, latency,
time to first token, prompt and completion token counts. **Never message
content**: prompts may contain drawings, part numbers or customer data. Two tests
enforce this for the gateway (`test_logs_never_contain_message_content`) and the
agent (`test_agent_logs_omit_task_text`). Content capture, if ever needed, should be a
separate, opt-in, access-controlled store with retention rules, not the log stream.

Caller-supplied `x-request-id` values are reused only if they match
`[A-Za-z0-9._-]{1,64}`, so a client cannot inject newlines or forged fields into logs.

## Metrics

| Metric | Labels | Use |
|---|---|---|
| `gateway_requests_total` | tenant, model, status | error rate per tenant, 429 rate |
| `gateway_request_seconds` | model, stream | end-to-end latency seen by callers |
| `gateway_time_to_first_token_seconds` | model | streaming responsiveness; compare with vLLM's own TTFT to see queueing |
| `gateway_tokens_total` | tenant, model, kind | usage and chargeback |
| `gateway_upstream_failures_total` | upstream, reason | a backend failing over silently is still a backend failing |
| `gateway_quota_rejections_total` | tenant | quota tuning |

## Known limits

- **Quotas are per replica.** With N replicas a tenant can get up to N× its quota.
  The fix is a shared counter: Redis, or Limitador when the gateway runs behind
  Kuadrant. Not done here because it adds a stateful dependency to a demo stack.
- **Token charging happens after the response.** A tenant can overdraw by one
  request. Reserving `prompt + max_tokens` up front is stricter but penalises
  callers who set a high `max_tokens` and use little of it.
- **Failover is per request, not per token.** Once a stream has started, a
  backend failure ends the stream; the client retries.
- **No model-aware load balancing.** Upstreams are tried in order. Spreading load
  across vLLM replicas by queue depth or KV-cache usage is what the Gateway API
  Inference Extension (InferencePool + endpoint picker, used by llm-d) does, and
  it belongs below this gateway, not inside it.

## Performance

Measured in [`results/gateway-overhead.json`](../results/gateway-overhead.json),
method in [`benchmark.md`](benchmark.md). Short version: about 1.5–1.7 ms added
per request on a laptop at concurrency 1 (median of 3 repeats), against model
calls that take hundreds of milliseconds to seconds. The first version
re-serialised every streamed event to rename the model field. Forwarding bytes
unchanged and parsing only the events that carry content or usage halved the
added streaming latency at 8 concurrent streams (+16.1 → +7.8 ms, 206 → 401
req/s). At 32 concurrent streams the single worker is saturated either way and
the two versions are within run-to-run noise; the fix there is more replicas.

## Build or adopt

This gateway is small on purpose, so every behaviour above is visible and
tested. On a real cluster I would not run it alone:

| Option | What it gives | Where it fits |
|---|---|---|
| [Envoy AI Gateway](https://aigateway.envoyproxy.io/) | Envoy-based, configured with Kubernetes CRDs; unified API over several providers, token-based rate limiting, upstream credential injection | cluster edge for LLM traffic when Envoy Gateway is already the ingress |
| [LiteLLM proxy](https://docs.litellm.ai/docs/simple_proxy) | Python OpenAI-compatible proxy over many providers; virtual keys, budgets, fallbacks; needs a database for keys and spend | teams mixing hosted APIs and self-hosted models, where per-key budgets matter |
| [Kuadrant](https://kuadrant.io/) | Gateway API policies: AuthPolicy (Authorino), RateLimitPolicy (Limitador), token-based limits in recent releases | OpenShift clusters already on Gateway API; shared, multi-replica quotas |
| [Gateway API Inference Extension](https://gateway-api-inference-extension.sigs.k8s.io/) | model-aware routing to vLLM pods (queue depth, KV-cache, LoRA adapters) | between the gateway and the model servers, regardless of which gateway is used |

What stays in application code either way: the agent's tool registry, argument
validation, approval rules and run records. Those depend on what the tools do,
which no gateway knows.
