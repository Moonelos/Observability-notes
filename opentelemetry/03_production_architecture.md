# Production Architecture

OpenTelemetry can export directly from an SDK to a backend, but production
systems usually put an OpenTelemetry Collector between services and backends.

The Collector is not just another agent. It is the control point for telemetry:

```text
services
  -> OTLP exporters
  -> Collector receivers
  -> Collector processors
  -> Collector exporters
  -> trace, metric, log, and LLM observability backends
```

This chapter explains how to design that pipeline so it is understandable,
operable, and safe.

## 📦 What The Collector Owns

The Collector owns shared telemetry policy. It should not own application
meaning. Application services still create spans, metrics, logs, attributes, and
context. The Collector receives those signals and applies infrastructure policy.

| Concern | Usually owned by |
| --- | --- |
| Span names and business attributes | Application instrumentation |
| Metric instruments and labels | Application instrumentation |
| Service identity | Application resource configuration, sometimes enriched by Collector |
| Propagation between services | Application SDK and instrumentations |
| Batching, retry, queueing | SDK and Collector |
| Redaction and attribute cleanup | Collector, with app-side defense too |
| Routing to backends | Collector |
| Tail sampling | Collector |
| Backend credentials | Collector or secret manager |
| Alerts and dashboards | Metrics/log/trace backends |

If the Collector is the first place that knows whether an operation was a RAG
retrieval, an agent tool call, or an LLM generation, the app is under-
instrumented. If every service hardcodes backend credentials and routing, the
platform is under-architected.

> 💡 **Key insight:** If the Collector has to infer what an operation was from raw attributes, your application is under-instrumented — span names and business attributes belong in the service, not in Collector transforms.

## 📦 Collector Components

Collector config is built from components. Components are configured at the top
level and enabled in `service.pipelines`.

| Component | Direction | Examples |
| --- | --- | --- |
| Receiver | Into the Collector | `otlp`, `prometheus`, `filelog`, `hostmetrics`. |
| Processor | Between receiver and exporter | `memory_limiter`, `batch`, `attributes`, `resource`, `transform`, `tail_sampling`. |
| Exporter | Out of the Collector | `otlphttp`, `prometheus_remote_write`, `debug`, vendor exporters. |
| Connector | Between pipelines | Span-derived metrics, routing, pipeline fan-in/fan-out. |
| Extension | Collector capability | `health_check`, `pprof`, `zpages`, auth extensions. |

The `service` section enables components:

```yaml
service:
  extensions: [health_check]
  pipelines:
    traces:
      receivers: [otlp]
      processors: [memory_limiter, batch]
      exporters: [otlphttp/traces]
```

A configured component that is not referenced in a pipeline is not active.
Processor order matters.

## 🗺️ Common Topologies

### Direct Export

```text
service -> OTLP exporter -> backend
```

Use this for local development, prototypes, or very small systems.

Pros:

- simplest deployment;
- fewer moving parts;
- good for first tests.

Cons:

- backend endpoints and credentials live in every service;
- changing routing requires redeploying services;
- redaction and sampling policies are duplicated;
- fan-out is harder;
- backend outages can affect every service directly.

### Local Agent Or Sidecar Collector

```text
service -> local Collector -> backend
```

The Collector runs near the workload: same host, same VM, sidecar container, or
Kubernetes DaemonSet.

Use it when:

- services need a stable local endpoint;
- you want local buffering, retry, or redaction;
- host metrics and application telemetry should share a nearby pipeline;
- teams deploy services independently;
- network egress should be standardized through local infrastructure.

Tradeoff: every node or pod now runs a Collector, so you operate more Collector
instances. Keep local config small and push global policy to a gateway when the
system grows.

### Gateway Collector

```text
services -> Collector gateway -> backends
```

The Collector is a shared service, usually one per cluster, region, or
environment.

Use it when:

- many services share the same telemetry policy;
- backend credentials should be centralized;
- you need fan-out to several destinations;
- sampling, redaction, and routing should change without redeploying services;
- platform teams own observability infrastructure.

Tradeoff: the gateway becomes shared infrastructure. Scale it, load balance it,
and monitor it like any other production dependency.

### Agent-To-Gateway

```text
service -> local Collector -> gateway Collector -> backends
```

This is common at scale.

Local agent:

- receives app telemetry locally;
- batches and retries near the workload;
- collects host/container signals;
- forwards to a gateway.

Gateway:

- performs centralized redaction and routing;
- applies tail sampling;
- fans out to multiple backends;
- owns backend credentials.

This pattern gives both local resilience and centralized policy.

Which hop becomes unavailable when the shared telemetry network fails? This
agent-to-gateway deployment makes the ownership boundaries explicit:

```mermaid
flowchart LR
  subgraph Node[Application node]
    S[service process SDK] -->|OTLP to local endpoint| A[local agent Collector]
  end
  subgraph Shared[Shared telemetry network]
    G[gateway Collector]
  end
  A -->|batched OTLP over network| G
  G -->|export with backend credentials| B[Backend]
```

If the shared network fails, the service can still reach its local agent. The
agent's finite queue buffers accepted work until it fills or its retry deadline
expires; local reachability does not guarantee eventual backend receipt. Direct
to gateway removes that local buffering hop. A sidecar puts the same agent role
inside the application's pod, so pod termination also ends that buffer unless
its configured storage survives. A backend outage instead breaks the last hop;
the gateway's own finite queue is the next boundary to inspect.

## 🔀 Signal-Specific Pipelines

Do not assume traces, metrics, and logs should travel to the same backend.

Typical routing:

```text
traces -> trace backend and/or Langfuse
metrics -> Prometheus-compatible or vendor metrics backend
logs -> log search/storage backend
```

Collector pipelines are signal-specific:

```yaml
service:
  pipelines:
    traces:
      receivers: [otlp]
      processors: [memory_limiter, attributes/redact, batch]
      exporters: [otlphttp/traces]

    metrics:
      receivers: [otlp]
      processors: [memory_limiter, batch]
      exporters: [prometheus_remote_write]

    logs:
      receivers: [otlp]
      processors: [memory_limiter, attributes/redact, batch]
      exporters: [otlphttp/logs]
```

The same receiver can feed all three pipelines. The processors and exporters
should reflect each signal's needs.

### CloudWatch Logs As A Destination

The Collector Contrib distribution includes an `awscloudwatchlogs` exporter.
It uses the default AWS credential chain and can create the configured log group
and stream when they do not already exist:

```yaml
exporters:
  awscloudwatchlogs:
    log_group_name: "/services/{ServiceName}"
    log_stream_name: "{InstanceId}"
    region: "${env:AWS_REGION}"
    log_retention: 30

service:
  pipelines:
    logs:
      receivers: [otlp]
      processors: [memory_limiter, attributes/redact, batch]
      exporters: [awscloudwatchlogs]
```

`{ServiceName}` and `{InstanceId}` are replaced from the corresponding resource
attributes. `log_retention` applies only when the exporter creates a new log
group; manage existing groups separately. Confirm that the deployed Collector
distribution contains this exporter, grant only the required CloudWatch Logs
permissions, and validate the config against the exact Collector release. The
exporter's OpenTelemetry logging support is currently experimental.

## 🛠️ A Production Collector Config

This example:

- receives OTLP over gRPC and HTTP;
- exposes a health endpoint;
- protects memory;
- enriches resources with environment;
- redacts sensitive attributes from traces and logs;
- batches data;
- sends traces to Langfuse and a generic trace backend;
- sends metrics to Prometheus remote write;
- sends logs to a log backend.

```yaml
extensions:
  health_check:
    endpoint: 0.0.0.0:13133

receivers:
  otlp:
    protocols:
      grpc:
        endpoint: 0.0.0.0:4317
      http:
        endpoint: 0.0.0.0:4318

processors:
  memory_limiter:
    check_interval: 5s
    limit_mib: 1024
    spike_limit_mib: 256

  resource/add_environment:
    attributes:
      - key: deployment.environment.name
        value: production
        action: upsert

  attributes/drop_secrets:
    actions:
      - key: http.request.header.authorization
        action: delete
      - key: http.request.header.cookie
        action: delete
      - key: http.response.header.set_cookie
        action: delete
      - key: db.query.text
        action: delete
      - key: db.statement
        action: delete
      - key: user.email
        action: delete
      - key: exception.message
        action: delete
      - key: exception.stacktrace
        action: delete

  transform/redact_apm:
    error_mode: propagate
    trace_statements:
      - context: span
        statements:
          - delete_key(attributes, "gen_ai.system_instructions")
          - delete_key(attributes, "gen_ai.input.messages")
          - delete_key(attributes, "gen_ai.output.messages")
          - delete_key(attributes, "gen_ai.tool.definitions")
          - delete_key(attributes, "gen_ai.tool.call.arguments")
          - delete_key(attributes, "gen_ai.tool.call.result")
          - delete_key(attributes, "langfuse.observation.input")
          - delete_key(attributes, "langfuse.observation.output")
          - delete_key(attributes, "langfuse.trace.input")
          - delete_key(attributes, "langfuse.trace.output")
          - delete_key(attributes, "llm.prompts")
          - delete_key(attributes, "llm.completions")
    log_statements:
      - context: log
        statements:
          - delete_key(attributes, "gen_ai.system_instructions")
          - delete_key(attributes, "gen_ai.input.messages")
          - delete_key(attributes, "gen_ai.output.messages")
          - delete_key(attributes, "gen_ai.tool.definitions")
          - delete_key(attributes, "gen_ai.tool.call.arguments")
          - delete_key(attributes, "gen_ai.tool.call.result")
          - delete_key(attributes, "langfuse.observation.input")
          - delete_key(attributes, "langfuse.observation.output")
          - delete_key(attributes, "langfuse.trace.input")
          - delete_key(attributes, "langfuse.trace.output")
          - delete_key(attributes, "llm.prompts")
          - delete_key(attributes, "llm.completions")
          - set(body, "[REDACTED_BY_COLLECTOR]") where body != nil

  batch:
    timeout: 5s
    send_batch_size: 512

exporters:
  otlphttp/langfuse:
    endpoint: https://cloud.langfuse.com/api/public/otel
    headers:
      Authorization: "Basic ${env:LANGFUSE_AUTH_STRING}"
      x-langfuse-ingestion-version: "4"

  otlphttp/traces:
    endpoint: https://apm.example.com/otlp
    headers:
      api-key: "${env:APM_API_KEY}"

  prometheus_remote_write:
    timeout: 10m
    retry_on_failure:
      enabled: true
      initial_interval: 5s
      max_interval: 30s
      max_elapsed_time: 10m
    endpoint: https://prometheus.example.com/api/v1/write
    headers:
      authorization: "Bearer ${env:PROMETHEUS_TOKEN}"

  otlphttp/logs:
    endpoint: https://logs.example.com/otlp
    headers:
      api-key: "${env:LOGS_API_KEY}"

service:
  extensions: [health_check]
  pipelines:
    traces/langfuse:
      receivers: [otlp]
      processors: [memory_limiter, resource/add_environment, attributes/drop_secrets, batch]
      exporters: [otlphttp/langfuse]

    traces/apm:
      receivers: [otlp]
      processors: [memory_limiter, resource/add_environment, attributes/drop_secrets, transform/redact_apm, batch]
      exporters: [otlphttp/traces]

    metrics:
      receivers: [otlp]
      processors: [memory_limiter, resource/add_environment, batch]
      exporters: [prometheus_remote_write]

    logs:
      receivers: [otlp]
      processors: [memory_limiter, resource/add_environment, attributes/drop_secrets, transform/redact_apm, batch]
      exporters: [otlphttp/logs]
```

This is a deployment template with placeholder endpoints and credentials. For pinned Contrib 0.158.0, remote-write `endpoint` and `headers` belong directly under the exporter, as shown in the [release schema](https://github.com/open-telemetry/opentelemetry-collector-contrib/blob/v0.158.0/exporter/prometheusremotewriteexporter/README.md) (checked 2026-10-14); there is no nested `http` object. Validate using that exact distribution before supplying real destinations. This is the destination-specific split in configuration form. The same receiver feeds two trace pipelines. Langfuse receives approved, application-masked LLM input/output after universal secret fields are removed. The general APM backend receives the same trace shape, timing, status, model, and usage attributes after payload fields are removed. Named events now travel through the logs pipeline, where the same sensitive payload attributes are removed and every body is suppressed by default. Replace that conservative body rule only after defining and testing a log-body masker.

The historical .158 remote-write exporter couples the HTTP timeout to its
whole retry loop. Both bounds above are ten minutes to avoid the default
five-second loss boundary. This remains finite, non-durable buffering; use the
[controlled outage test and upgrade qualification](../examples/03_collector_prometheus_langfuse.md#qualify-remote-write-recovery-on-the-historical-pin)
before claiming backend recovery.

Watch where the same approved input diverges. The destination-specific transform sits only on the APM trace branch, and the log branch has its own body policy.

```mermaid
flowchart LR
  R[OTLP receiver: one SSO workflow] --> L[Langfuse branch: memory limit and resource enrichment]
  R --> A[APM branch: memory limit and resource enrichment]
  R --> G[Logs branch: memory limit and resource enrichment]
  L --> LS[drop_secrets: credentials and exception fields]
  A --> AS[drop_secrets: credentials and exception fields]
  G --> GS[drop_secrets: credentials and exception fields]
  LS --> LB[batch then otlphttp/langfuse]
  AS --> AR[redact_apm: remove input and output content]
  AR --> AB[batch then otlphttp/traces]
  GS --> GR[redact_apm: content keys plus body suppression]
  GR --> GB[batch then otlphttp/logs]
```

Langfuse retains application-masked model input because its branch removes universal secrets without the APM content transform. APM keeps the same span IDs, duration, status and usage, but loses the content fields before export. Logs remain a separate signal: their bodies are suppressed even if a trace's masked input is approved elsewhere. Moving the content transform before the fork would remove the approved rich payload from Langfuse too; moving it after either destination would be too late to enforce that destination's permission boundary. Processor instances belong to their pipeline, so this fork must be tested at both outputs.

"Rich" never means raw. Mask or allowlist question, prompt, document, tool, account, and output content in the application before it enters a span or log event. Collector deletion by key cannot find a secret embedded inside an otherwise allowed JSON string. Test both destinations with canary API keys, emails, authorization headers, exception messages, log-event attributes and bodies, legacy LLM keys, and Langfuse root/observation payloads.

> ⚠️ **Watch out:** Collector `attributes` processors delete by key name only — a secret embedded inside a JSON string value passes through untouched; mask or redact sensitive content in application code before it enters a span attribute.

Validate config before deploying:

```bash
otelcol validate --config=collector.yaml
```

A matching extracted template is [otel_collector_production.yaml](../examples/local/otel_collector_production.yaml). Validation against Contrib 0.158.0 with synthetic environment values succeeded on 2026-10-14; this checks the component schema, not remote credentials or destination permissions. [The local signal test](../examples/local/otel_collector_signal_test.py) executes the richer/redacted split with file destinations, a real SDK named log, and canary bodies/attributes. Its terminal PASS verifies local privacy and metric label behavior. It does not establish safe handling of arbitrary nested application JSON or remote backend storage.

In CI, validate every Collector config change. In production, deploy config
changes gradually because a bad telemetry config can create blind spots during
incidents.

## 🔄 Processor Order

A practical default order:

```text
memory_limiter
  -> resource enrichment
  -> deterministic noise filter
  -> universal secret redaction
  -> destination-specific redaction/transform
  -> sampling or routing
  -> batch
  -> exporters
```

Reasons:

- `memory_limiter` should run early so the Collector protects itself.
- resource enrichment should happen before routing rules that use resource attributes.
- known leaf/self-contained noise can be removed before paying for redaction
  and tail-sampling CPU, but only when the filter preserves trace shape;
- universal redaction must run before destination-specific transforms and
  before data crosses any trust boundary;
- tail sampling needs enough trace attributes available to make decisions.
- `batch` is usually near the end so exporters send efficient payloads.

Some processors are signal-specific. A processor referenced by multiple
pipelines gets a separate instance per pipeline.

**Upgrade context — GA, checked 2026-10-28:** OTTL (OpenTelemetry Transformation
Language), used by `transform/redact_apm`, reaches v1 in Contrib 0.164.0. Its
standard syntax and functions gain 1.x compatibility; experimental functions and
profiles remain outside that promise. This does not make every component using
OTTL stable, or change the historical 0.158.0 schema above. See the
[upgrade gates](deployment/06_security_operations_and_upgrades.md#6--upgrade-image-chart-and-config-separately)
before changing bundles. [OTTL v1 announcement](https://opentelemetry.io/blog/2026/ottl-v1/).

## 🗄️ Langfuse In A Collector Pipeline

Langfuse accepts traces through an OTLP HTTP endpoint. Use a Collector
`otlphttp` exporter that points at the Langfuse OTEL base endpoint:

```yaml
exporters:
  otlphttp/langfuse:
    endpoint: https://cloud.langfuse.com/api/public/otel
    headers:
      Authorization: "Basic ${env:LANGFUSE_AUTH_STRING}"
      x-langfuse-ingestion-version: "4"
```

The `otlphttp` exporter appends the signal path for the traces pipeline. Do not
append `/v1/traces` unless the specific exporter or backend configuration
requires it.

`x-langfuse-ingestion-version: "4"` selects real-time raw OTLP ingestion
on Langfuse's v4 data model; it is not a general OTLP requirement. Server v4
is GA as checked 2026-10-28. Without the header, data can take up to 15 minutes
to appear. For self-hosting, check the actual server version and ingestion
configuration, including any direct-ingestion override, rather than using
preview availability as the decision. The pinned Collector example retains the
header. Langfuse Cloud removes legacy ingestion on **2026-11-16**; qualify a
migration before that date. [Versions and compatibility](https://langfuse.com/docs/compatibility).

Important Langfuse routing rules:

- Send traces to Langfuse; send general metrics to a metrics backend.
- Langfuse can map `gen_ai.request.model`, `gen_ai.response.model`, and
  `gen_ai.usage.*` into generation fields.
- Use `langfuse.trace.metadata.*` or `langfuse.observation.metadata.*` when you
  need metadata to be filterable in Langfuse.
- Langfuse currently supports OTLP over HTTP/protobuf and HTTP/JSON for
  ingestion; OTLP/gRPC ingestion is not supported.

For privacy, it is common to fan out traces like this:

```text
traces with rich LLM payloads -> Langfuse
operational traces with redacted payloads -> APM backend
metrics -> metrics backend
logs -> log backend
```

If you send the same raw trace stream to multiple backends, every backend gets
the same sensitive attributes. Use a dedicated redacted pipeline when that is
not acceptable.

## 🔀 Routing And Fan-Out

Fan-out means sending one signal to multiple exporters:

```yaml
service:
  pipelines:
    traces:
      receivers: [otlp]
      processors: [memory_limiter, attributes/redact, batch]
      exporters: [otlphttp/traces, otlphttp/langfuse]
```

That is simple but coarse. Every exporter receives the same processed data.

When destinations need different data shapes, create separate pipelines or
route before redaction:

```text
raw trace stream
  -> pipeline A: preserve LLM payloads -> Langfuse
  -> pipeline B: remove LLM payloads -> APM backend
```

Exact routing mechanics depend on Collector distribution and available
processors/connectors. The design question is always the same: which backend is
allowed to receive which attributes?

## 🎲 Sampling Strategy

Sampling controls trace volume. It is not a substitute for metrics.

Start without sampling when possible. First learn:

- request volume by service and route;
- average spans per trace;
- error and latency distribution;
- backend cost;
- which attributes are needed for incident debugging.

Then sample intentionally.

### Head Sampling

Head sampling is decided at trace start, usually in the SDK:

```text
root span starts
  -> sampler decides sampled or not sampled
  -> child spans follow parent decision
```

Pros:

- simple;
- cheap;
- can be configured in SDKs;
- preserves whole traces when parent-aware.

Cons:

- cannot know future errors;
- cannot know final latency;
- cannot keep all traces matching attributes added later.

Use it for broad volume reduction when losing some interesting traces is
acceptable. Prefer parent-aware probability sampling.

### Remove Deterministic Noise Before Sampling

Filtering and sampling solve different problems. Suppress a span at the source
when it is proven to be useless; use a Collector filter for telemetry that has
already been produced; use tail sampling when the decision must preserve or
drop the complete trace coherently.

Typical candidates are successful liveness/readiness probes, metrics scrapes,
static assets, and framework-internal heartbeat spans. Source exclusion saves
SDK allocation, exporter queue space, network bandwidth, and Collector CPU, but
it also removes every matching status. Before enabling it, verify that failed
probe traces are either still required or fully covered by metrics and logs,
that the instrumentation does not also suppress required HTTP metrics, and that
the handler cannot create unrelated root spans through child instrumentation.

When source suppression is too broad, a service- and route-specific Collector
filter can remove only successful noise:

```yaml
processors:
  filter/successful_probes:
    error_mode: ignore
    trace_conditions:
      - >
        resource.attributes["service.name"] == "my-api" and
        IsMatch(span.attributes["http.route"],
                "^/(health|healthz|live|ready|metrics)$") and
        span.attributes["http.response.status_code"] == 200
```

Prefer the stable `http.route` template over span name and include service and
outcome in the predicate. The filter processor removes individual spans, not
complete traces. Dropping a parent can orphan children and correlated logs, so
span filters belong only on verified leaf or self-contained telemetry. Use a
trace-aware policy when the endpoint performs instrumented downstream work.

### Tail Sampling

Tail sampling decides after the Collector has seen most or all spans in a trace:

```text
spans arrive
  -> Collector buffers by trace ID
  -> rules evaluate the complete trace
  -> keep or drop
```

Common policies:

- keep all error traces;
- keep traces above a latency threshold;
- keep traces from a new release;
- keep traces with specific routes, models, tenants, or feature flags;
- sample the remaining normal traffic probabilistically.

Example policy sketch:

```yaml
processors:
  tail_sampling:
    decision_wait: 10s
    policies:
      - name: keep-errors
        type: status_code
        status_code:
          status_codes: [ERROR]
      - name: keep-slow
        type: latency
        latency:
          threshold_ms: 5000
      - name: sample-rest
        type: probabilistic
        probabilistic:
          sampling_percentage: 5
```

For a fuller Collector-side example that samples on exact attribute values,
error types, token and cost thresholds, release burn-in, tenant tiers, and
guardrail outcomes, see
[../examples/03_collector_prometheus_langfuse.md](../examples/03_collector_prometheus_langfuse.md).

Tail sampling requirements:

- all spans for a trace must reach the same sampling decision point;
- the Collector must hold traces in memory until the decision;
- `decision_wait` must exceed measured p99 complete-trace arrival time plus
  SDK/export/network jitter;
- Collector memory, queue sizes, and dropped spans must be monitored.

Choose production values from measurements, not from the `5%`, `10s`, or other
numbers in examples. Record at least:

- new traces per second, including high-volume routes and workflows;
- average and p95 spans per trace;
- p99 complete-trace arrival time;
- error and slow-trace rates measured from full-fidelity metrics;
- serialized bytes per span or trace;
- critical outcomes and the minimum useful daily sample per route/workflow;
- backend ingest/retention budget and expected outage-buffer window.

A first capacity model is:

```text
daily retained spans
  ~= traces_per_second
     * average_spans_per_trace
     * 86,400
     * effective_retained_ratio

minimum active trace capacity
  ~= traces_per_second
     * decision_wait_seconds
     * burst_headroom
```

Important policies overlap, so measure the effective retained ratio from
Collector output instead of adding configured percentages. Size sampled and
non-sampled decision caches above the active trace buffer when late spans are
possible, and load-test memory, early drops, late spans, and decision latency.
If measurements do not exist yet, label the policy provisional and state what
must be measured before it can be called production-ready.

At scale, use trace-ID-aware load balancing before the tail-sampling tier so all
spans for the same trace land on the same Collector instance.

Watch where spans for trace `abc123` meet. The router must choose the same sampler for both services, even if the spans arrive in different OTLP batches.

```mermaid
flowchart LR
  A[chat-api trace abc123] -->|root and client spans| R[trace-ID-aware routing tier]
  B[retrieval trace abc123] -->|server span| R
  R -->|hash abc123| T1[tail sampler 1]
  R -->|other trace IDs| T2[tail sampler 2]
  T1 -->|retained complete trace| O[trace backend]
  T2 -->|retained traces| O
```

Sampler 1 can now see that retrieval failed and retain the containing chat request. A round-robin router could send the successful root to sampler 1 and the failing child to sampler 2; each makes a decision from incomplete evidence. Hash the trace ID, not the OTLP request, client IP, or persistent connection. Changing sampler membership can change the hash mapping while traces are still arriving. Drain and canary topology changes, measure complete-trace arrival time, and follow the deployment guide's rollout continuation rather than assuming consistent hashing prevents every in-flight split.


> ⚠️ **Watch out:** Tail sampling silently produces incomplete traces if spans for the same trace arrive at different Collector replicas — you must route by trace ID before the tail-sampling tier, not by standard round-robin.

### Trace Sampling Does Not Sample Logs

Sending traces and logs through the same Collector does not give them a shared
sampling decision. Collector pipelines are signal-specific, and the standard
tail-sampling processor operates on traces:

```yaml
service:
  pipelines:
    traces:
      receivers: [otlp]
      processors: [tail_sampling, batch]
      exporters: [otlphttp/traces]

    logs:
      receivers: [otlp]
      processors: [batch]
      exporters: [awscloudwatchlogs]
```

Suppose the application emits this telemetry:

```text
trace abc123
  span: POST /chat
  log: request started, trace_id=abc123
  log: provider call completed, trace_id=abc123
```

If `tail_sampling` rejects trace `abc123`, the log records still continue
through the logs pipeline:

```text
CloudWatch Logs -> records with trace_id=abc123
trace backend   -> no stored trace abc123
```

These are sometimes called orphan logs: their trace context is valid, but the
corresponding trace was not retained. The shared Collector provides routing and
correlation fields; it does not make storage retention atomic across signals.
The same outcome is possible when a backend expires traces sooner than logs.

#### Head Sampling And The Sampled Flag

An OTel log record can contain `TraceId`, `SpanId`, and `TraceFlags`. With head
sampling, the `SAMPLED` flag is known when the log is emitted. The OTel Logs SDK
specification defines a development `trace_based` logger setting that drops a
correlated log when it has a valid span ID and its sampled flag is unset.

Use that behavior only when the chosen language SDK or logging bridge implements
it and dropping those logs is intentional. It does not affect standalone logs
without trace context, and it is not a universal Collector setting. For
non-OTLP structured logs, include `trace_flags` as well as `trace_id` and
`span_id` if downstream filtering needs the head decision.

#### Tail Sampling Cannot Reuse The Head Decision

Tail sampling decides after spans have reached the Collector. A log may already
have been exported before that decision exists. In the common design where the
SDK records all candidate traces, their logs arrive with the head sampled flag
set; a later tail rejection cannot retroactively change that flag or recall the
logs.

Exact tail-aligned retention requires a stateful cross-signal component that:

1. buffers logs by `trace_id`;
2. waits for the trace sampling decision;
3. releases or drops the buffered logs with that decision;
4. handles untraced logs, late spans, timeouts, restarts, and missing decisions.

That is custom infrastructure, not a normal pair of Collector pipelines. It
adds memory pressure, log latency, ordering and recovery problems, and a larger
temporary store of potentially sensitive data. Use it only when a strict
retention requirement justifies that operational cost.

#### Log Severity Is Not Span Status

Log severity and span status are separate fields. This statement:

```python
logger.error("provider failed")
```

does not by itself set the active span to `ERROR`. A tail policy that keeps
error-status traces needs the failed operation to record trace-side failure
semantics:

```python
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

tracer = trace.get_tracer(__name__)


def call_provider_safely():
    with tracer.start_as_current_span(
        "provider.request", record_exception=False
    ) as span:
        try:
            return call_provider()
        except Exception as exc:
            span.set_status(Status(StatusCode.ERROR))
            span.set_attribute("error.type", type(exc).__qualname__)
            # The log pipeline owns the exception details and stack trace.
            logger.exception("provider call failed")
            return None
```

An SDK context manager can still create a legacy exception span event when an
exception escapes. New manual instrumentation should pass
`record_exception=False`, keep `set_status_on_exception=True`, and emit the
exception through the correlated logs pipeline. When code catches the exception
inside the span, as above, set the final span status explicitly if the operation
truly failed and let the structured exception log carry the stack trace.
Do not mark every span as failed merely because it emitted an error-level log: a
successful fallback can make the containing operation successful even though a
child operation failed.

A handled 4xx response normally means the service enforced its contract, not
that the server span failed. Decide explicitly how timeouts, cancellations, and
client disconnects map to span status and a bounded `app.outcome`; apply the
same policy in trace attributes, metrics, and logs. Test failure paths directly:
an error-biased sampler cannot retain a trace whose failed boundary remained
`UNSET`.

> 💡 **Key insight:** `logger.error(...)` does not set the active span to ERROR — span status and log severity are completely independent fields that must both be set explicitly when an operation fails.

#### Recommended Production Default

Prefer independent, importance-aware retention:

```text
traces
  -> keep 100% of failed and slow traces
  -> keep traces with critical bounded attributes
  -> probabilistically sample normal traffic

logs
  -> keep operational WARN/ERROR records
  -> sample or drop noisy INFO/DEBUG records
  -> redact sensitive bodies and attributes
```

Make important failures visible in both signals: emit a structured error log and
set the relevant span status or bounded `error.type`. Accept that an ordinary
informational log may point to a trace that was not retained. Correlation depends
on correct trace context and backend retention, not on traces and logs passing
through the same Collector.

### Critical Outcomes, Diagnostics, And Policy Ownership

Retain critical outcomes using bounded attributes that exist before the tail
decision: route templates, workflow names, immutable `service.version`,
guardrail results, fallback use, step-limit stops, bounded error types, and
approved usage thresholds. Low-volume critical workflows may require 100%
retention even when high-volume normal traffic keeps much less.

A forced diagnostic trace is an operational privilege. Accept it only from an
authenticated internal control with an allowlisted attribute, audit record,
owner, expiry, and automatic removal. Never trust a public header, queue field,
or caller-supplied baggage value to force retention. Raw user, tenant, request,
session, conversation, and workflow-run IDs are not general sampling
dimensions; use bounded tiers or cohorts unless a trace-only identity use has
explicit privacy approval.

Keep the policy in version control with its owner, rationale, thresholds,
expected volume, start/review dates, and expiry for temporary release-burn-in or
diagnostic rules. Review it when traffic, routes, workflows, models,
instrumentation, or backend pricing changes.

## 📊 Metrics Are Not Sampled Traces

Do not build alerting totals only from sampled traces. A 5 percent trace sample
cannot accurately tell you exact request volume, token volume, error rate, or
SLO burn.

Emit metrics independently:

```text
traces -> sampled for investigation cost control
metrics -> complete aggregate signal for dashboards and alerts
logs -> searchable local details and audit-style records
```

Span-derived metrics can be useful for convenience, but they should be treated
carefully if the traces are sampled before derivation.

## 🗺️ Scaling The Collector

Scale the Collector like a production service.

Watch:

- CPU and memory;
- accepted, refused, and dropped spans/metrics/logs;
- exporter queue size;
- exporter send failures;
- batch size and latency;
- tail sampling decision latency;
- receiver request rate;
- backend throttling or 4xx/5xx responses.

Horizontal scale:

```text
services -> load balancer -> gateway Collector replicas -> backends
```

For most pipelines, any Collector replica can process any request. Tail sampling
is the exception: trace spans must be consistently routed to the same sampling
replica.

Collector capacity depends on:

- signal volume;
- spans per trace;
- attribute size;
- processor cost;
- exporter latency;
- backend throughput;
- queue and retry settings;
- tail sampling decision windows.

Large attributes, especially LLM prompts and outputs, can dominate bandwidth and
memory. Decide early where those payloads are allowed and how much to truncate.

## 🔀 Resilience And Backpressure

Telemetry should help production; it should not take production down.

Use:

- `memory_limiter` to protect Collector memory;
- batching to reduce exporter overhead;
- exporter queues and retry where available;
- local agents when network links are unreliable;
- backend rate-limit monitoring;
- load shedding policies when telemetry volume spikes.

Understand failure modes:

| Failure | Result |
| --- | --- |
| Collector down and SDK has no retry/buffer | Service may drop telemetry. |
| Backend down | Collector queues then drops when queue fills. |
| Collector overloaded | Refused or dropped telemetry, higher memory and CPU. |
| Redaction misconfigured | Sensitive data may leave the network. |
| Tail sampler underprovisioned | Incomplete or dropped traces. |

Telemetry loss is usually preferable to application downtime, but silent
telemetry loss during an incident is painful. Alert on Collector self-telemetry.

## 🔒 Security And Privacy

Secure the Collector as production infrastructure:

- bind receivers to private networks when possible;
- do not expose OTLP, pprof, zPages, or debug endpoints publicly;
- use TLS or mTLS for cross-network traffic;
- keep exporter credentials in secret managers or environment variables;
- restrict who can change Collector config;
- validate config in CI;
- redact or hash sensitive attributes before telemetry leaves your network;
- avoid raw prompts and retrieved documents in general APM backends;
- allowlist baggage keys and treat incoming baggage as untrusted;
- use separate pipelines when different backends have different data permissions.

Common sensitive fields:

- authorization headers;
- cookies;
- API keys;
- session tokens;
- full URLs with query strings;
- request and response bodies;
- raw prompts and completions;
- retrieved document contents;
- emails and names;
- payment, health, or contractual data.

For LLM systems, privacy is an architecture decision, not an instrumentation
afterthought. Decide which backend is allowed to receive prompt and completion
payloads, how masking works, who can access the data, and how long it is
retained.

Hashing is not automatically anonymization. Delete low-entropy personal fields
such as email by default: an attacker can cheaply enumerate likely inputs to an
unsalted hash. When a stable pseudonym is genuinely required, create it before
telemetry emission with a reviewed keyed HMAC, key rotation, access controls,
and a retention policy. Collector redaction remains a second line of defense,
not the only control.

## 🔍 Collector Self-Telemetry

The Collector emits its own logs and metrics. Scrape or export them.

Useful questions:

- Is the Collector receiving telemetry?
- Is it dropping data?
- Are exporters failing?
- Are queues filling?
- Is memory close to the limiter?
- Is tail sampling making decisions in time?
- Did a config rollout change throughput?

Expose health checks for orchestration and use internal metrics for alerts.

Example operational alerts:

- Collector exporter send failures above zero for 10 minutes.
- Collector dropped spans or metric points above zero.
- Exporter queue utilization above 80 percent.
- Collector memory above 85 percent of limit.
- Tail sampling late decisions or policy errors.
- OTLP receiver request errors or refused data.

## 🗺️ Deployment Patterns

For copyable Docker and Kubernetes baselines, image/distribution selection,
Helm-versus-Operator guidance, Service discovery, scaling, security, upgrades,
and runbooks, use the dedicated
[Collector Deployment Guide](deployment/README.md).

### Kubernetes

Common Kubernetes shapes:

| Pattern | Description |
| --- | --- |
| Sidecar | Collector runs in the same pod as the app. Strong isolation, more resource overhead. |
| DaemonSet | One Collector per node. Good for local node-level collection. |
| Deployment gateway | Shared Collector service. Good for central policy and fan-out. |
| Agent-to-gateway | DaemonSet or sidecar forwards to gateway. Common at scale. |

Kubernetes checklist:

- services export to a stable Collector DNS name;
- requests and limits are set for Collector pods;
- HPA or manual scaling is based on Collector metrics;
- config is managed through versioned manifests;
- receivers are not exposed through public load balancers;
- pod, namespace, node, and cluster resource attributes are added or detected;
- tail sampling receives all spans for a trace on the same tier.

### VMs Or Bare Metal

Common non-Kubernetes shape:

```text
service process -> local Collector service -> regional gateway -> backends
```

Use system service management for the local Collector, and keep app exporter
endpoints stable on localhost or a local network address.

### Serverless

Serverless functions need special care:

- cold starts must configure OTel once per runtime instance;
- the function must flush before freeze/exit if telemetry is buffered;
- direct export may be simpler than a local Collector;
- managed layers or extensions may provide instrumentation;
- keep payload capture small because invocation time matters.

## 🌐 Environment Separation

Separate environments explicitly:

```text
deployment.environment.name = development | staging | production
service.namespace = payments | search | llm-platform
service.version = git sha or semver
```

Do not mix staging and production in the same dashboards without a clear
environment label. Do not use the same exporter credentials for all
environments unless your backend permissions are intentionally shared.

## ✅ Operational Checklist

Before production:

- Every service sets `service.name`, version, instance ID, and environment.
- SDKs export to a local or gateway Collector.
- Collector config is validated in CI.
- Receivers bind to private networks.
- Collector has health checks.
- Collector self-telemetry is scraped and alerted on.
- `memory_limiter` and `batch` processors are present.
- Sensitive attributes are removed, hashed, or routed only to approved backends.
- Trace context propagates across HTTP, gRPC, queues, and workers.
- Sampling policy is documented and tested.
- Sampling percentages, thresholds, decision windows, trace capacity, and
  exporter queues are justified by measured traffic and budget.
- Temporary release-burn-in and diagnostic rules have an owner and expiry.
- Metrics are emitted independently from traces.
- Short-lived workloads flush on shutdown.
- Backends are tested with realistic telemetry volume.
- A complete golden trace is searchable in every intended backend, and canary
  secrets are absent from every destination.
- The Collector configuration is canaried with a tested rollback path before a
  fleet-wide rollout.

During incidents:

- Start with metric dashboards and alerts.
- Pivot to traces for examples.
- Use logs for local details and stack traces.
- Check Collector self-telemetry if data looks missing.
- Check recent deploys, prompt versions, model routes, and backend status.
- Verify whether sampling or redaction changed visibility.

## 🔍 Production Failure Modes

No telemetry reaches backend:

- SDK exporter endpoint is wrong.
- Collector receiver is not enabled in `service.pipelines`.
- Network policy blocks service-to-Collector traffic.
- Exporter credentials are missing.
- Backend rejects payloads.

Telemetry reaches Collector but not backend:

- exporter is not listed in the pipeline;
- exporter endpoint or headers are wrong;
- backend rate limits or rejects payloads;
- processor drops or filters data unexpectedly;
- queue fills and data is dropped.

Traces are incomplete:

- propagation is broken at service boundaries;
- tail sampling tier does not receive all spans for a trace;
- SDK shuts down before spans flush;
- a service exports to a different Collector or backend;
- span limits drop large attributes or links, or log-record limits drop event attributes.

Metrics are expensive:

- high-cardinality attributes are used;
- resource attributes include per-request values;
- histograms use too many dimensions;
- backend converts dotted names and labels unexpectedly;
- duplicate instrumentation records the same metric twice.

Sensitive data appears in a backend:

- app set raw content as span attributes;
- baggage carried unsafe values downstream;
- Collector redaction ran after fan-out;
- a backend received the raw pipeline instead of the redacted one;
- prompts and outputs were enabled without a masking policy.

## Recap and decisions

Application code creates meaning and correlation. The Collector applies signal-specific transport and retention policy. Affinity makes a tail decision coherent; it does not align log retention or recover spans that the SDK already discarded. Redaction must precede the destination that cannot receive content, while queues buy a finite outage interval.

### Check yourself

1. A failed retrieval and its successful root reach different samplers. Why is “retain errors” insufficient?
2. An ERROR log reached CloudWatch before its trace was rejected. What remains?
3. At 2,000 spans/s, a queue holds 120,000 spans and the backend stops. How long is the nominal buffer?

<details><summary>Reasoned answers</summary>

1. Each sampler sees only its own fragment. One can retain the failure without the root; the other can drop the successful root. Routing must assemble the trace before deciding.
2. The log remains with valid correlation IDs. Standard tail sampling has no authority to recall it; cross-signal retention needs an explicit stateful buffer.
3. `120,000 / 2,000 = 60s` before burst, memory, retry, batch-size, or queue-unit effects. This is a planning bound, not an availability guarantee; test the actual exporter units and outage recovery throughput.

</details>

### Try it: change the trust boundary

A new APM contract prohibits prompt content, while Langfuse may receive masked content. Choose between one shared pipeline with two exporters and separate destination pipelines. Sketch the redaction position and describe a canary test without real secrets.

<details><summary>Worked decision</summary>

A shared pipeline sends identical processed records to both exporters, so it either leaks content to APM or removes the approved Langfuse payload too. Split the traces pipeline; remove universal secrets on both, then remove content on the APM branch. Inject synthetic canary markers into attributes, named log-event bodies, exception strings and nested JSON. Inspect every destination and confirm the forbidden markers are absent. A key-only deletion test cannot establish nested-value privacy.

</details>

**Next**: Apply this architecture with the
[Collector Deployment Guide](deployment/README.md), then continue to
[Multi-Service Examples](04_multi_service_examples.md).
