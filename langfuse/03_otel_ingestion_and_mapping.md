# OpenTelemetry Ingestion and Attribute Mapping

Routing/filtering checked against official sources on 2026-10-14; mapping baseline checked on 2026-07-24.

Role: implementation. Read [OTel context/export](../opentelemetry/02_python_instrumentation.md)
and [Langfuse's object model](01_overview_data_model.md) first. The SDK smoke in 02 proves a
local tree; this chapter adds a destination boundary. Collector configuration examples require
the pinned Collector distribution and private receiver networking taught in the deployment path.
Raw experiment blocks below are application-dependent excerpts, not a standalone experiment runner.

## 🧭 Mental Model

Raw OpenTelemetry ingestion is the interoperability path into Langfuse. For a vendor-neutral implementation, applications emit normal OpenTelemetry spans and send OTLP only to an OpenTelemetry Collector. Standard semantic conventions and organization-owned attributes form the application contract; destination-specific attributes, credentials, endpoints, and exporters belong in Collector configuration.

Use this mental model:

```text
application spans
  standard OTel + gen_ai.* + app.*
  -> OTLP to Collector
       |-- general pipeline -----------------> APM backend
       `-- GenAI workflow pipeline
             -> Langfuse-only attribute mapping
             -> OTLP/HTTP to Langfuse
```

The application does not know whether the general backend is Groundcover, AWS X-Ray, Jaeger, Tempo, or another OTLP-compatible destination. Replacing a backend changes Collector configuration, not instrumentation code.

> 💡 **Key insight:** With this architecture, swapping Langfuse for a different observability backend — or adding one — requires only a Collector config change, not a code deployment.

Langfuse can ingest OpenTelemetry traces directly over OTLP/HTTP. Use this when:

- your service is not Python or JavaScript/TypeScript;
- your organization already emits OTel spans from many services;
- you want the Collector to route GenAI traces to Langfuse;
- you want standard OTel instrumentation with Langfuse mapping isolated to one Collector pipeline.

This path does not provide the Langfuse SDK's convenience methods for prompt management, datasets, experiments, or scoring. Services or workers that use those APIs become intentionally Langfuse-aware; keep that decision separate from the vendor-neutral tracing path.

## 📐 Vendor-Neutral Application Contract

Framework independence and backend independence are separate:

- Framework-independent code does not depend on LangChain, LangGraph, LlamaIndex, or another LLM framework.
- Backend-independent code does not contain Langfuse SDK calls, Langfuse credentials or endpoints, or `langfuse.*` attributes.

Use the most widely understood attribute contract available:

| Meaning | Application attribute strategy |
| --- | --- |
| service and deployment identity | Standard resource attributes such as `service.name`, `service.version`, and `deployment.environment.name` |
| HTTP, database, messaging, and RPC work | The corresponding OpenTelemetry semantic conventions |
| model operations and usage | Current OpenTelemetry GenAI attributes such as `gen_ai.operation.name`, `gen_ai.provider.name`, `gen_ai.request.model`, and `gen_ai.usage.*` |
| user and session correlation | Standard attributes such as `user.id` and `session.id`, subject to privacy policy |
| product and business dimensions | A documented organization-owned namespace such as `app.*` |
| whole-trace routing intent | A neutral, low-cardinality marker such as `app.telemetry.category="genai"` |

Example application instrumentation:

```python
from opentelemetry import trace

tracer = trace.get_tracer(__name__)

with tracer.start_as_current_span("agent.run") as root:
    root.set_attribute("app.telemetry.category", "genai")
    root.set_attribute("app.workflow.name", "chat.answer")
    root.set_attribute("app.trace.dimension.tenant_tier", "enterprise")
    root.set_attribute("user.id", "opaque-user-123")
    root.set_attribute("session.id", "opaque-session-456")
    root.set_attribute("http.route", "/chat")

    with tracer.start_as_current_span("chat provider-model-name") as generation:
        generation.set_attribute("gen_ai.operation.name", "chat")
        generation.set_attribute("gen_ai.provider.name", "provider-name")
        generation.set_attribute("gen_ai.request.model", "provider-model-name")
        generation.set_attribute("gen_ai.usage.input_tokens", 820)
        generation.set_attribute("gen_ai.usage.output_tokens", 164)
        generation.set_attribute(
            "app.observation.dimension.feature_variant",
            "reranker_v2",
        )
        run_model_call()
```

There are no framework callbacks, Langfuse imports, Langfuse keys, or Langfuse attribute names in this code. The same spans can be exported to multiple backends unchanged.

The snippet sets workflow dimensions on the root for readability. If those dimensions must be filterable on child observations, propagate and copy them onto the relevant spans using the allowlisted baggage pattern below.

Prefer a standard semantic convention over an equivalent `app.*` attribute. Use `app.*` only for stable product semantics that OpenTelemetry does not define. Document whether each custom value is trace-wide or observation-specific; the Collector cannot infer that distinction from a generic key.

Vendor-neutral does not mean every backend provides the same experience from the same raw attribute. In Langfuse, unmapped span attributes remain inspectable under catch-all metadata, but their nested keys are not directly filterable. The Langfuse pipeline therefore copies selected neutral attributes into Langfuse's first-class schema without changing the source contract.

## 🔄 Lifecycle of a Raw OTLP Trace

1. Your service starts a root span for the user-visible workflow.
2. The service records standard OTel attributes plus documented `app.*` workflow and business dimensions.
3. Child spans record operations: retrievers, generations, tools, guardrails, chains, agents, and ordinary service work.
4. Generation spans use current OpenTelemetry GenAI attributes for operation, provider, model, and usage.
5. Trace context travels across services with W3C headers.
6. Selected neutral correlation dimensions travel with baggage and are copied to relevant spans through an explicit allowlist.
7. The Collector routes complete GenAI workflow traces, or an explicitly classified rooted GenAI view, into the Langfuse pipeline.
8. Only that pipeline adds any required `langfuse.*` attributes and exports to Langfuse over OTLP/HTTP.
9. Other pipelines export the original standard and `app.*` attributes to their own backends.
10. Langfuse maps the enriched spans into observations and makes the workflow available for inspection, scoring, datasets, and metrics.

The hard part is not exporting bytes. It is preserving a complete trace while maintaining one stable application schema and applying backend-specific mappings only at destination boundaries.

## 🔌 Langfuse Endpoint in the Collector

Langfuse supports OTLP over HTTP with JSON or protobuf. OTLP/gRPC is not supported.

> ⚠️ **Watch out:** Configuring an OTLP/gRPC exporter pointed at Langfuse will silently fail — Langfuse only accepts OTLP/HTTP.

In the vendor-neutral architecture, configure the base endpoint on the Collector's Langfuse exporter, not in the application environment:

```yaml
exporters:
  otlphttp/langfuse:
    endpoint: https://cloud.langfuse.com/api/public/otel
```

The `otlphttp` exporter appends `/v1/traces`. A direct, signal-specific exporter instead uses `https://cloud.langfuse.com/api/public/otel/v1/traces`. Use the correct base URL for your Langfuse region or self-hosted instance. Current Langfuse Cloud regions include EU (`https://cloud.langfuse.com`), US (`https://us.cloud.langfuse.com`), Japan (`https://jp.cloud.langfuse.com`), and HIPAA (`https://hipaa.cloud.langfuse.com`).

## 🔒 Langfuse Authentication in the Collector

Langfuse uses Basic Auth where the username is the public key and the password is the secret key. Inject their base64-encoded `public_key:secret_key` value into the Collector secret `LANGFUSE_AUTH_STRING`:

```yaml
exporters:
  otlphttp/langfuse:
    headers:
      Authorization: "Basic ${env:LANGFUSE_AUTH_STRING}"
      x-langfuse-ingestion-version: "4"
```

The `x-langfuse-ingestion-version: 4` header selects Langfuse's current ingestion path for direct OTel spans.

Security rules:

- Store `LANGFUSE_AUTH_STRING` as a secret or inject it at runtime; do not commit encoded keys.
- Inject Langfuse credentials only into the Collector deployment, not application containers.
- Keep Collector receivers private.
- Use TLS to Langfuse and TLS/mTLS or network policy between applications and Collectors.
- Treat OTel headers as credentials when they contain Langfuse Basic Auth.

## 🛠️ Direct Python Exporter: Vendor-Coupled Alternative

The following direct exporter is useful for a small proof of concept, but it is not the recommended implementation when backend independence is a requirement. It places the Langfuse endpoint, authentication, and ingestion behavior in application configuration. In the vendor-neutral design, the application instead uses a normal OTLP exporter pointed at the Collector.

As written, this minimal exporter sends every recorded span on its provider to Langfuse.
For a mixed application, apply the [destination wrapper](#the-same-filtering-without-a-collector)
below to this exporter before attaching it to `BatchSpanProcessor`.

```python
import os
from base64 import b64encode

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor


def configure_langfuse_otlp() -> TracerProvider:
    auth = b64encode(
        f"{os.environ['LANGFUSE_PUBLIC_KEY']}:{os.environ['LANGFUSE_SECRET_KEY']}".encode()
    ).decode()

    provider = TracerProvider(
        resource=Resource.create(
            {
                "service.name": "agent-service",
                "service.version": os.getenv("RELEASE", "local"),
                "deployment.environment.name": os.getenv("ENVIRONMENT", "dev"),
            }
        )
    )
    provider.add_span_processor(
        BatchSpanProcessor(
            OTLPSpanExporter(
                endpoint=f"{os.getenv('LANGFUSE_BASE_URL', 'https://cloud.langfuse.com')}/api/public/otel/v1/traces",
                headers={
                    "Authorization": f"Basic {auth}",
                    "x-langfuse-ingestion-version": "4",
                },
            )
        )
    )
    trace.set_tracer_provider(provider)
    return provider
```

This vendor-coupled example creates a direct exporter from one Python process to Langfuse. Retain the returned provider and flush it in short-lived work:

```python
provider = configure_langfuse_otlp()
try:
    run_job()
finally:
    provider.force_flush(timeout_millis=30_000)
    provider.shutdown()
```

`BatchSpanProcessor` exports asynchronously. Without `force_flush()` or `shutdown()`, the last batch from a CLI, test, worker, or serverless invocation can remain in memory when the process exits. In long-running services, call `shutdown()` once from the process lifespan hook. For the vendor-neutral production path, configure the application exporter with the Collector's OTLP endpoint and keep destination authentication, redaction, retry, batching, and routing in the Collector.

## 🔗 Langfuse Destination Mapping Reference

Raw OpenTelemetry spans become Langfuse observations. The following attributes map fields into first-class Langfuse concepts, but in the vendor-neutral design the Collector adds them; application code does not.

```text
neutral input                                  Langfuse pipeline adds
app.workflow.name="chat.answer"                langfuse.trace.name="chat.answer"
app.trace.dimension.tenant_tier="enterprise"   langfuse.trace.metadata.tenant_tier="enterprise"
app.trace.tags=["chat", "production"]           langfuse.trace.tags=["chat", "production"]
service.version="2026.07.24-1"                  langfuse.release="2026.07.24-1"
```

For raw OTLP, encode structured input/output values as JSON strings if the exporter does not support nested values.

### Per-Call Input Fidelity

The repeated-history behavior is not specific to Langfuse. In the OpenTelemetry
GenAI conventions, `gen_ai.input.messages` means the chat history provided to
one model invocation, in the order sent. If a stateless agent resends the full
history for every model call, provider-faithful inference spans repeat that
history before any Langfuse mapping happens.

OTel content capture is opt-in, and instrumentations may allow the input to be
filtered or truncated. A compact capture is therefore possible, but it must not
be presented as the complete model request:

- Keep `gen_ai.input.messages` in the standard message-array schema even when
  only a delta or truncated view is retained.
- Add an organization-owned field such as
  `app.gen_ai.input.capture_mode="delta"` so the Collector and reviewers know
  that the payload is incomplete.
- Use `gen_ai.conversation.compacted=true` only when the context sent to the
  model was actually compacted, not when telemetry alone was shortened.
- Do not assume every backend version promotes
  `gen_ai.input.messages` into its first-class input field. Test the pinned
  Langfuse version and, when necessary, map the selected value explicitly to
  `langfuse.observation.input` only in the Langfuse destination pipeline.

This lets one neutral application contract support two Langfuse views: exact
per-call input for debugging/replay, or a deliberately labeled compact view for
human review. The root observation can still carry the user message and final
answer, while tool observations carry arguments/results.

Layered explanation:

- Beginner intuition: attributes are the labels and payloads Langfuse uses to understand a span.
- Technical mechanics: the Langfuse-only Collector transform adds `langfuse.*` attributes for destination-specific concepts; standard GenAI semantic conventions already provide model and usage details.
- Production implications: attribute names become a contract across services and dashboards.
- Common mistakes: adding vendor attributes in application code, relying on arbitrary OTel attributes to become filterable metadata, and sending arrays/maps through exporters that do not support them.

## 🔗 Trace-Level Mapping

Common trace-level attributes:

| Langfuse field | OTel attribute |
| --- | --- |
| trace name | `langfuse.trace.name` |
| user ID | `langfuse.user.id` or `user.id` |
| session ID | `langfuse.session.id` or `session.id` |
| release | `langfuse.release` |
| version | `langfuse.version` |
| tags | `langfuse.trace.tags` |
| public trace flag | `langfuse.trace.public` |
| filterable metadata | `langfuse.trace.metadata.<key>` |

For accurate Langfuse filtering and aggregation, propagate important trace-level attributes to every span in the trace. If only a leaf span has `user_id`, metrics grouped by user can become incomplete.

Langfuse v4 has no separate trace input or output entity. Put the overall request and response on the root observation using `langfuse.observation.input` and `langfuse.observation.output` if the capture policy permits it. If application code must remain vendor-neutral, define and document neutral root input/output attributes, then map them in the Collector; do not copy arbitrary payload-bearing attributes by default.

Layered explanation:

- Beginner intuition: trace-level attributes are the shared facts about the whole workflow.
- Technical mechanics: Langfuse can detect trace attributes on spans, but filters and aggregations increasingly operate at observation level, so every relevant span should carry them.
- Production implications: use a consistent neutral propagation strategy at the root of every request and perform Langfuse enrichment after propagation.
- Common mistakes: setting correlation attributes only on the root span, mapping them only on a generation span, or storing values as nested metadata that cannot be filtered.

## 📦 Observation Mapping

Common observation attributes:

| Langfuse field | OTel attribute |
| --- | --- |
| observation type | `langfuse.observation.type` |
| observation level | `langfuse.observation.level` or span status |
| status message | `langfuse.observation.status_message` or span status message |
| observation input | `langfuse.observation.input` |
| observation output | `langfuse.observation.output` |
| observation metadata | `langfuse.observation.metadata.<key>` |
| model | `langfuse.observation.model.name`, `gen_ai.request.model`, `gen_ai.response.model`, `llm.model_name`, or `model` |
| provider | `gen_ai.provider.name` |
| model parameters | `langfuse.observation.model.parameters`, `gen_ai.request.*`, or `llm.invocation_parameters.*` |
| input tokens | `gen_ai.usage.input_tokens` |
| output tokens | `gen_ai.usage.output_tokens` |
| usage details | `langfuse.observation.usage_details` or `gen_ai.usage.*` |
| cost details | `langfuse.observation.cost_details` or `gen_ai.usage.cost` |
| prompt link | `langfuse.observation.prompt.name` and `langfuse.observation.prompt.version` |
| environment | `langfuse.environment`, `deployment.environment`, or `deployment.environment.name` |

Use current OpenTelemetry GenAI semantic convention names for new code, especially `gen_ai.provider.name`, `gen_ai.operation.name`, `gen_ai.request.model`, and `gen_ai.usage.*`.

Layered explanation:

- Beginner intuition: observation attributes describe one step, not the whole workflow.
- Technical mechanics: a model attribute or `langfuse.observation.type="generation"` tells Langfuse to treat a span as a generation.
- Production implications: accurate observation mapping drives trace readability, token/cost charts, and model-level comparisons.
- Common mistakes: missing model or usage data, using only legacy GenAI fields in new code, and putting step-specific metadata on the trace.

## 🔗 Propagating Trace Attributes with Baggage

OpenTelemetry trace context connects spans across services. Baggage can carry selected neutral correlation dimensions so downstream services can copy the same fields onto their spans before the Collector performs destination-specific mapping.

Gateway:

```python
from opentelemetry import baggage, propagate, trace

tracer = trace.get_tracer(__name__)

with tracer.start_as_current_span("gateway.request") as span:
    span.set_attribute("app.workflow.name", "agent.answer")
    span.set_attribute("app.trace.dimension.tenant_tier", "enterprise")
    span.set_attribute("user.id", "opaque-user-123")
    span.set_attribute("session.id", "opaque-session-abc")

    ctx = baggage.set_baggage("app.workflow.name", "agent.answer")
    ctx = baggage.set_baggage(
        "app.trace.dimension.tenant_tier",
        "enterprise",
        context=ctx,
    )
    ctx = baggage.set_baggage("user.id", "opaque-user-123", context=ctx)
    ctx = baggage.set_baggage("session.id", "opaque-session-abc", context=ctx)

    headers: dict[str, str] = {}
    propagate.inject(headers, context=ctx)
```

Downstream service:

```python
from opentelemetry import baggage, propagate, trace

tracer = trace.get_tracer(__name__)


def handle(headers: dict[str, str]) -> None:
    ctx = propagate.extract(headers)
    with tracer.start_as_current_span("agent.execute", context=ctx) as span:
        for key in (
            "app.workflow.name",
            "app.trace.dimension.tenant_tier",
            "user.id",
            "session.id",
        ):
            value = baggage.get_baggage(key, context=ctx)
            if value:
                span.set_attribute(key, value)
```

Never copy arbitrary baggage into span attributes. Use a small allowlist and exclude secrets, raw personal data, prompts, retrieved documents, and other payloads. Baggage is transmitted in request headers and can cross service boundaries.

Recommended production options:

- In vendor-neutral OTel services, set neutral baggage at the workflow entry point and use explicit allowlist copying or an organization-owned span processor.
- In multi-service systems, instrument HTTP clients and servers so W3C trace context and baggage are injected/extracted automatically.
- Keep baggage values short, non-sensitive, and stable.
- Map the resulting span attributes in the Langfuse Collector pipeline, after they have been copied onto every observation where filtering is required.

Langfuse SDK propagation helpers are appropriate for the intentionally vendor-coupled SDK and framework paths described in [06_framework_integrations.md](06_framework_integrations.md). Do not use them in a service whose tracing contract must remain backend-independent.

## See which pipeline owns each copy

The two-ingress topology answers which destinations receive an ordinary workflow and which receive
a complete GenAI workflow. The GenAI receiver carries roots, retrievals, tools and generations:

```mermaid
flowchart LR
  N["ordinary workflows"] --> O["OTLP receiver 4317 / 4318"]
  G["complete SSO GenAI workflow"] --> R["OTLP genai receiver 4327 / 4328"]
  subgraph C["trusted Collector"]
    O --> A["APM pipeline: neutral fields"]
    R --> A
    R --> T["Langfuse transform: copy app fields"]
  end
  A --> P["APM backend"]
  T --> L["Langfuse OTLP HTTP + Basic Auth"]
```

Both streams reach APM; only the complete GenAI stream enters the Langfuse transform.
The transform creates destination fields without renaming the original `app.*` fields. Therefore
APM still understands the neutral contract. Filtering to generation leaves before routing would
remove `rag.answer` and `rag.retrieve`: the model receipt would survive but the evidence needed to
diagnose the stale SSO source would disappear.

A baggage header is a transport carrier, not stored observation metadata. The downstream service
must make the handoff explicit before a destination transform can copy it:

```mermaid
sequenceDiagram
  participant G as Gateway
  participant H as HTTP carrier
  participant R as RAG service
  participant C as Langfuse pipeline
  G->>H: inject traceparent + approved tenant tier baggage
  H->>R: receive enterprise tier
  R->>R: extract context before creating spans
  R->>R: allowlist and copy tier to app.trace.dimension.tenant_tier
  R->>C: root + children with neutral attributes
  C->>C: copy to langfuse.trace.metadata.tenant_tier
```

The same traceparent joins the request; copying tier makes it searchable. A header-supplied tier
cannot authorize an enterprise feature: derive trusted values from application authentication,
and reject or replace untrusted external baggage. The transform cannot recover a field that was
never copied onto the needed spans.

## 📐 Collector-Owned Routing and Vendor Mapping

A common production pattern sends ordinary operational traces to the general tracing backend and sends complete LLM/agent workflow traces to Langfuse. The general backend can also receive the complete GenAI stream when operators need end-to-end service diagnostics there.

The example uses two neutral Collector ingress endpoints:

- `otlp` receives ordinary service telemetry;
- `otlp/genai` receives complete GenAI workflow traces, including their root, HTTP, retrieval, tool, guardrail, and generation spans.

Applications know only which Collector ingress class to use. They do not know either destination. The `transform/langfuse` processor is referenced only by the Langfuse pipeline and copies neutral attributes into the Langfuse schema.

```yaml
receivers:
  otlp:
    protocols:
      grpc:
        endpoint: 0.0.0.0:4317
      http:
        endpoint: 0.0.0.0:4318
  otlp/genai:
    protocols:
      grpc:
        endpoint: 0.0.0.0:4327
      http:
        endpoint: 0.0.0.0:4328

processors:
  memory_limiter:
    check_interval: 1s
    limit_mib: 512
  transform/langfuse:
    error_mode: ignore
    trace_statements:
      - set(span.attributes["langfuse.trace.name"], span.attributes["app.workflow.name"]) where span.attributes["app.workflow.name"] != nil
      - set(span.attributes["langfuse.trace.tags"], span.attributes["app.trace.tags"]) where span.attributes["app.trace.tags"] != nil
      - set(span.attributes["langfuse.trace.metadata.tenant_tier"], span.attributes["app.trace.dimension.tenant_tier"]) where span.attributes["app.trace.dimension.tenant_tier"] != nil
      - set(span.attributes["langfuse.observation.metadata.feature_variant"], span.attributes["app.observation.dimension.feature_variant"]) where span.attributes["app.observation.dimension.feature_variant"] != nil
      - set(span.attributes["langfuse.release"], resource.attributes["service.version"]) where resource.attributes["service.version"] != nil
  batch:
    timeout: 5s
    send_batch_size: 1024

exporters:
  otlphttp/langfuse:
    endpoint: https://cloud.langfuse.com/api/public/otel
    headers:
      Authorization: "Basic ${env:LANGFUSE_AUTH_STRING}"
      x-langfuse-ingestion-version: "4"
  otlphttp/apm:
    endpoint: https://traces.example.com/otlp
    tls:
      insecure: false

service:
  pipelines:
    traces/apm:
      receivers: [otlp, otlp/genai]
      processors: [memory_limiter, batch]
      exporters: [otlphttp/apm]
    traces/langfuse:
      receivers: [otlp/genai]
      processors: [memory_limiter, transform/langfuse, batch]
      exporters: [otlphttp/langfuse]
```

The transform uses current path-qualified OTTL syntax. Pin and test the Collector distribution because the transform processor is a Collector Contrib component and its configuration support depends on the deployed version.

The mapping rules add destination attributes; they do not rename or delete the standard and `app.*` attributes. Consequently:

- the APM pipeline receives the original vendor-neutral schema;
- the Langfuse pipeline receives that schema plus Langfuse-specific enrichment;
- standard `gen_ai.*` fields pass through unchanged because Langfuse already maps them;
- replacing Langfuse or the APM backend requires exporter and transform changes only.

The example maps only an explicit allowlist. Add mappings when a concrete Langfuse filter or workflow needs them; do not mirror every application attribute into `langfuse.trace.metadata.*`.

GenAI services send all spans for a GenAI workflow to port 4327/4328; ordinary workflows use 4317/4318. Both receiver streams reach the APM backend, while only the complete GenAI stream reaches Langfuse. Protect both receivers on the private network.

If one service mixes GenAI and non-GenAI workflows and cannot choose an ingress endpoint per workflow, choose complete-trace selection or the explicit rooted view below. A root marker evaluated by a trace-aware component can select a complete trace; a span filter requires the marker on every span it must retain. Baggage alone does not populate span attributes. A filter that keeps only spans containing `gen_ai.request.model` discards parents, retrievers, tools, and guardrails.

> ⚠️ **Watch out:** Filtering by individual span attributes (like model name) instead of by complete trace routes the LLM leaf spans to Langfuse while silently dropping the root, retriever, and tool spans needed to understand them.

### Keep a rooted GenAI view instead of operational subtrees

Filtering Langfuse's destination independently is a useful architecture choice when HTTP,
database and persistence spans make AI workflows noisy. The `otel-observability` skill's
`references/collector/genai_projection.md` applies this policy. It is a project contract,
not a universal OTel requirement that Langfuse receive only attributes named `gen_ai.*`.

For one mixed `/chat` request, the APM backend gets the complete tree. The Langfuse view
keeps the root, the business operation explaining the model call, and the model:

```mermaid
flowchart LR
    S["one /chat trace: 5 spans"] --> A["APM: all 5 spans"]
    S --> F["GenAI destination filter"]
    F --> L["Langfuse: POST /chat → answer question → chat demo-model"]
    F --> D["omit load documents and persist answer siblings"]
```

Every retained span must retain its entire parent chain to the root: this is an
**ancestor-closed** view. All IDs, parent IDs, timestamps and status stay unchanged.
The root and `answer question` keep their true semantics; do not invent
`gen_ai.operation.name` on them just to pass a filter. A log referencing an omitted
DB span still uses its actual span ID and remains correlatable in APM.

Use `app.telemetry.category="genai"` as explicit membership in this view: set it on
the root, workflow/agent/model/retrieval/tool spans and every intermediate parent.
Ordinary `/health` traces and operational-only sibling subtrees remain unmarked.
Do not inherit membership indiscriminately onto every child, or the DB/HTTP noise returns.
For synchronous multi-service traces, each service must classify the required ancestors;
if it cannot, send the complete workflow trace instead. A Collector filter cannot
reconstruct a missing parent or infer ancestry from the model span's attributes.

Add this processor to the Collector's Langfuse branch only. This is an excerpt for
Collector Contrib **0.159.0**, using its current condition syntax; validate against
the exact deployed image before merging it into an older config:

```yaml
processors:
  filter/genai_projection:
    error_mode: ignore
    trace_conditions:
      - 'span.attributes["app.telemetry.category"] != "genai"'

service:
  pipelines:
    traces/langfuse:
      receivers: [otlp]
      processors: [memory_limiter, filter/genai_projection, transform/langfuse, batch]
      exporters: [otlphttp/langfuse]
```

Conditions mean **drop**, so missing markers are removed too. Leave the APM branch
unfiltered and redact its verbose AI payloads separately. For tail sampling, evaluate
the retention policy on the complete trace before applying the destination projection;
otherwise an operational error you removed can no longer influence that decision.
`error_mode: ignore` skips a failing condition and can allow spans through; this filter
is destination selection, not a substitute for mandatory secret redaction.
The [pinned filter documentation](https://github.com/open-telemetry/opentelemetry-collector-contrib/blob/v0.159.0/processor/filterprocessor/README.md)
defines the syntax and warns about orphaned telemetry.

### The same filtering without a Collector

Use one `TracerProvider` with independent destination processors. The APM processor
receives all recorded spans; the Langfuse processor receives the marked view. Never use
the provider's sampler to suppress non-GenAI spans just for Langfuse: head sampling
affects every destination and only sees attributes available when the span starts.

With the Langfuse Python SDK, configure the filter at initialization:

```python
from langfuse import Langfuse
from genai_destination_filter import keep_genai_view  # examples/local module

# provider already owns the ordinary APM BatchSpanProcessor.
langfuse = Langfuse(
    tracer_provider=provider,
    should_export_span=keep_genai_view,
)
```

This callback replaces the SDK default. The SDK's current default accepts Langfuse,
GenAI and recognized LLM instrumentation spans; it reduces infrastructure noise but
does not prove that ordinary application parents survive. For a deliberate rooted
view, explicitly mark every selected ancestor and use the membership callback.
Compose with `is_default_export_span` only if you also intend to accept its broader
set. See [Langfuse filtering](https://langfuse.com/docs/observability/sdk/advanced-features).

With **raw OTel and no Langfuse SDK**, the plain OTLP exporter has no Langfuse
`should_export_span` option. Wrap only the Langfuse destination's exporter:

```python
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from genai_destination_filter import GenAIViewExporter

# langfuse_otlp is the authenticated OTLP/HTTP exporter configured above.
provider.add_span_processor(
    BatchSpanProcessor(GenAIViewExporter(langfuse_otlp))
)
```

The wrapper delegates export, flush and shutdown, filters ended `ReadableSpan`s and
never mutates spans shared with other processors. This version filters after batching:
unselected spans still consume the branch's queue capacity. A custom filtering processor
before batching can avoid that overhead, but must preserve the SDK processor lifecycle.
Direct export also moves credentials, retry/queue budgets, mapping and redaction into
the application deployment. Keep those policies explicit; the example verifies routing
and contains no real payloads. The unfiltered APM branch in this local canary is not a
production payload-redaction implementation.

Run the complete local canary in the SDK environment from chapter 02:

```bash
/tmp/langfuse-notes-venv/bin/python examples/local/genai_destination_filter.py
```

The [canonical script](../examples/local/genai_destination_filter.py) runs both raw-OTel
and real Langfuse SDK filtering with in-memory destinations. Each produces `APM=6,
GenAI=3`: five `/chat` spans plus an unrelated `/health` root go to APM, while only
the three connected AI-view spans go to the GenAI destination. Assertions check IDs,
parents, timestamps, absence of orphaned children, and a named correlated log event.
This proves local SDK export behavior, not Collector execution or backend indexing.

The [Collector canary](../examples/local/verify_genai_projection.py) separately validates
the same condition against Contrib 0.159.0, sends real OTLP to a loopback receiver,
and checks both exported span sets using local files:

```bash
/tmp/langfuse-notes-venv/bin/python examples/local/verify_genai_projection.py /path/to/otelcol-contrib
```

Expected: `PASS Collector 0.159.0: APM=6, GenAI=3; full parent chain and original span fields preserved`.
It requires that exact binary and the OTLP/HTTP trace exporter installed in chapter 02.
It tests the filtering mechanism; production redaction, sampling, network security and
Langfuse indexing still need the deployed canary.

Before rollout, send a mixed canary through the deployed path and verify both backends:
complete APM tree, same trace ID in Langfuse, one retained root, every retained parent
present, and operational siblings absent. Track exporter failures/drops and queue
pressure independently for each destination. Restore complete-workflow export if
classification is incomplete rather than silently reparenting observations.

<details>
<summary>Check yourself: a new HTTP span is inserted between answer question and the model. Can it remain unmarked?</summary>

No. It becomes an ancestor of a retained model span, so omitting it breaks the parent
chain. Mark that HTTP span too, or preserve the complete workflow. An unrelated HTTP
sibling can remain unmarked. Retention depends on ancestry, not the library name.

</details>

Architecture responsibilities:

| Component | Responsibility |
| --- | --- |
| Application | Create meaningful spans using standard OTel, `gen_ai.*`, and documented `app.*` attributes; propagate trace context; export only to the Collector. |
| Collector receiver | Accept OTLP from trusted internal services only. |
| Shared Collector processors | Limit memory, normalize resources, redact sensitive attributes, and batch data consistently. |
| Destination processors | Add only the mappings and policy required by that backend, such as `transform/langfuse`. |
| Collector exporters | Own backend endpoints, credentials, protocol details, retry behavior, and delivery. |
| Langfuse | Map spans into LLM traces, observations, metrics, and evaluation workflows. |

Use Collector routing when platform teams need centralized backend selection or cost control. SDK-level `should_export_span` is part of a Langfuse-coupled implementation and is not the right boundary for the vendor-neutral path.

## 📁 Langfuse-Coupled Raw-OTLP Dataset Experiment

This section is outside the vendor-neutral tracing boundary. Langfuse dataset identity, experiment attributes, and score APIs are product-specific features, so a worker that uses them is intentionally Langfuse-aware. Keep such code in a dedicated evaluation component rather than leaking its contract into general application instrumentation.

Use the Langfuse experiment runner in Python or TypeScript when possible. For another runtime that emits raw OTLP, model each dataset item as a separate root trace. Never create one enclosing span for the whole experiment.

The following Python example shows the wire contract. `BaggageSpanProcessor` copies only the listed experiment keys to new spans:

```python
import json
import os
from base64 import b64encode
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx
from opentelemetry import baggage, context, trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.trace import SpanProcessor, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor


class ExperimentBaggageSpanProcessor(SpanProcessor):
    ALLOWED_PREFIXES = ("langfuse.experiment.",)
    ALLOWED_KEYS = {"langfuse.environment"}

    def on_start(self, span, parent_context=None):
        ctx = parent_context or context.get_current()
        for key, value in baggage.get_all(context=ctx).items():
            if key in self.ALLOWED_KEYS or key.startswith(self.ALLOWED_PREFIXES):
                span.set_attribute(key, value)

    def on_end(self, span):
        pass

    def shutdown(self):
        pass

    def force_flush(self, timeout_millis=30_000):
        return True


@dataclass(frozen=True)
class Item:
    id: str
    version: datetime
    input: dict
    expected_output: dict
    metadata: dict


auth = b64encode(
    f"{os.environ['LANGFUSE_PUBLIC_KEY']}:{os.environ['LANGFUSE_SECRET_KEY']}".encode()
).decode()
provider = TracerProvider()
provider.add_span_processor(ExperimentBaggageSpanProcessor())
provider.add_span_processor(
    BatchSpanProcessor(
        OTLPSpanExporter(
            endpoint=(
                f"{os.environ['LANGFUSE_BASE_URL'].rstrip('/')}"
                "/api/public/otel/v1/traces"
            ),
            headers={
                "Authorization": f"Basic {auth}",
                "x-langfuse-ingestion-version": "4",
            },
        )
    )
)
trace.set_tracer_provider(provider)
tracer = provider.get_tracer("raw-otel-experiment")
dataset_version = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)

experiment_ctx = context.Context()  # No active span: every item starts a new trace.
for key, value in {
    "langfuse.experiment.id": "exp-support-rag-v18",
    "langfuse.experiment.name": "support-rag-prompt-v18",
    "langfuse.experiment.dataset.id": "dataset-id-from-langfuse",
    "langfuse.experiment.description": "Pinned dataset regression",
    "langfuse.experiment.metadata.candidate": "prompt-v18",
    "langfuse.environment": "experiment",
}.items():
    experiment_ctx = baggage.set_baggage(key, value, context=experiment_ctx)


def run_item(item: Item) -> None:
    root = tracer.start_span("experiment-item", context=experiment_ctx)
    trace_id = format(root.get_span_context().trace_id, "032x")
    root_span_id = format(root.get_span_context().span_id, "016x")
    item_version = item.version.isoformat()

    item_attributes = {
        "langfuse.experiment.item.id": item.id,
        "langfuse.experiment.item.root_observation_id": root_span_id,
        "langfuse.experiment.item.version": item_version,
    }
    for key, value in item_attributes.items():
        root.set_attribute(key, value)
    root.set_attribute("langfuse.observation.input", json.dumps(item.input))
    root.set_attribute(
        "langfuse.experiment.item.expected_output",
        json.dumps(item.expected_output),
    )
    root.set_attribute(
        "langfuse.experiment.item.metadata.segment",
        str(item.metadata["segment"]),
    )

    item_ctx = experiment_ctx
    for key, value in item_attributes.items():
        item_ctx = baggage.set_baggage(key, value, context=item_ctx)
    item_ctx = trace.set_span_in_context(root, item_ctx)

    token = context.attach(item_ctx)
    try:
        # Instrumented child generations/tools inherit experiment and item baggage.
        output = run_instrumented_task(item.input)
        root.set_attribute("langfuse.observation.output", json.dumps(output))
    finally:
        context.detach(token)
        root.end()

    # Scores target both the item trace and its root observation.
    httpx.post(
        f"{os.environ['LANGFUSE_BASE_URL']}/api/public/scores",
        auth=(os.environ["LANGFUSE_PUBLIC_KEY"], os.environ["LANGFUSE_SECRET_KEY"]),
        json={
            "traceId": trace_id,
            "observationId": root_span_id,
            "name": "required_citations_present",
            "value": 1,
            "dataType": "BOOLEAN",
        },
        timeout=10,
    ).raise_for_status()


try:
    for item in pinned_items:
        assert item.version == dataset_version
        run_item(item)
finally:
    provider.force_flush(timeout_millis=30_000)
    provider.shutdown()
```

Register `ExperimentBaggageSpanProcessor` before starting any spans. For a Langfuse-managed dataset, use the dataset and item IDs returned by Langfuse and set every item's `version` to the exact fetched dataset version timestamp. Local datasets may use stable local correlation IDs but must omit item version. Input, actual output, and expected output belong on the item root; experiment/item identity belongs in baggage so child spans participate in the same experiment.

## 🗺️ Post-Transform OTLP Shape at the Langfuse Boundary

The application does not build this vendor-enriched payload. The Collector produces it after `transform/langfuse`, and the conceptual shape helps debug the Langfuse boundary:

```json
{
  "resourceSpans": [
    {
      "resource": {
        "attributes": {
          "service.name": "agent-service",
          "service.version": "sha-6f4c2d1",
          "deployment.environment.name": "prod"
        }
      },
      "scopeSpans": [
        {
          "spans": [
            {
              "name": "llm.generate_answer",
              "attributes": {
                "app.workflow.name": "rag.answer",
                "app.trace.dimension.tenant_tier": "enterprise",
                "user.id": "opaque-user-8f3a",
                "langfuse.trace.name": "rag.answer",
                "langfuse.trace.metadata.tenant_tier": "enterprise",
                "langfuse.release": "sha-6f4c2d1",
                "gen_ai.provider.name": "openai",
                "gen_ai.request.model": "provider-model-name",
                "gen_ai.usage.input_tokens": 820,
                "gen_ai.usage.output_tokens": 164
              }
            }
          ]
        }
      ]
    }
  ]
}
```

The real OTLP encoding may be protobuf or JSON. Before the transform, the same span contains the neutral source attributes; after the transform, it also contains the required Langfuse mapping attributes.

## ⚠️ Mapping Pitfalls

- Sending OTLP/gRPC to Langfuse. Use OTLP/HTTP.
- Missing Basic Auth or using secret/public keys in the wrong order.
- Using `LANGFUSE_HOST` in new examples. Use `LANGFUSE_BASE_URL`.
- Putting Langfuse credentials, endpoints, or `langfuse.*` attribute names in vendor-neutral application code.
- Renaming or deleting neutral attributes during Langfuse mapping instead of copying them into destination fields.
- Setting trace attributes only on one span and expecting complete Langfuse metrics.
- Using legacy `gen_ai.system` for new instrumentation instead of `gen_ai.provider.name`.
- Treating a filtered `gen_ai.input.messages` payload as the complete model request, or using `gen_ai.conversation.compacted` for telemetry-only truncation.
- Sending raw prompts, retrieved documents, or user data without privacy review.
- Filtering out the root span in the Collector.
- Using attribute path segments named `__proto__`, `constructor`, or `prototype`. Langfuse silently drops those segments; rename them during normalization, for example to `proto_name`, `constructor_name`, or `prototype_name`.
- Treating Langfuse as a metrics backend for all OTel metrics. Langfuse is trace and LLM workflow focused; send operational metrics to a metrics backend.

## 🔍 Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| `4xx` from Langfuse OTLP endpoint | Wrong credentials, wrong base URL, missing Basic Auth, unsupported self-hosted version | Rebuild `LANGFUSE_AUTH_STRING` from `public:secret`, verify region/self-hosted URL, upgrade self-hosted Langfuse. |
| Exporter cannot connect or gets protocol errors | Using OTLP/gRPC to Langfuse | Use OTLP/HTTP JSON or protobuf endpoint. |
| Trace appears without model/cost usage | Application did not emit current GenAI model/usage fields, or the backend does not map a required field | Emit standard `gen_ai.request.model`, provider, operation, and `gen_ai.usage.*`; add a destination mapping only for remaining Langfuse-specific gaps. |
| Metadata is visible but not filterable | A neutral attribute reached Langfuse catch-all metadata without an explicit mapping | Add an allowlisted copy into `langfuse.trace.metadata.<key>` or `langfuse.observation.metadata.<key>` in `transform/langfuse`. |
| APM receives `langfuse.*` attributes | The Langfuse transform was placed in a shared pipeline or applications emitted vendor fields | Keep the transform only in `traces/langfuse` and remove vendor-specific instrumentation from applications. |
| Only leaf generations appear | Collector filter dropped root/business spans | Route the complete trace using a neutral marker such as `app.telemetry.category="genai"` and keep all required parent spans. |
| Cross-service trace splits into multiple traces | W3C trace context not propagated/extracted | Instrument HTTP clients/servers or manually inject/extract context. |
| User/session filters miss spans | Neutral correlation attributes were not propagated to all relevant spans | Use neutral baggage plus explicit allowlist copying before Collector mapping. |
| Sensitive headers/documents appear | Redaction processor missing or ordered too late | Redact before exporting to Langfuse and logs; add tests for representative payloads. |
| Generation input looks complete but cannot reproduce the call | Instrumentation emitted only a delta or truncated message list without a capture marker | Preserve the standard message-array schema and add a bounded `app.gen_ai.input.capture_mode`; retain full input only where policy permits replay. |

## ✅ OTLP Production Checklist

- Point applications only at trusted Collector OTLP receivers.
- Keep vendor endpoints, credentials, headers, and attribute mapping out of application code.
- Use standard OpenTelemetry semantic conventions first, current `gen_ai.*` conventions for model telemetry, and documented `app.*` keys only for missing product semantics.
- Use OTLP/HTTP, not OTLP/gRPC, for direct Langfuse ingestion.
- Set Basic Auth as `public_key:secret_key` and include `x-langfuse-ingestion-version=4`.
- Choose the correct regional or self-hosted `/api/public/otel` endpoint.
- Create a root workflow span and preserve it through Collector filters.
- Propagate W3C trace context and only allowlisted neutral baggage across services.
- Copy required workflow names, release/version fields, tags, and filterable metadata into the Langfuse schema only inside `traces/langfuse`.
- Pass directly supported user, session, environment, and standard GenAI fields through unchanged; map only unsupported or organization-specific fields.
- Redact sensitive attributes before export.
- Route operational metrics to a metrics backend and logs to a log backend.
- Validate Collector config and test both exported shapes in staging: the APM payload must remain vendor-neutral, and the Langfuse payload must contain the expected first-class mappings.

## 🔌 Official References

- Langfuse OpenTelemetry integration: <https://langfuse.com/integrations/native/opentelemetry>
- Langfuse v4 custom OTEL ingestion migration: <https://langfuse.com/integrations/native/opentelemetry/migration-to-v4>
- SDK overview and OTel foundation: <https://langfuse.com/docs/observability/sdk/overview>
- SDK advanced span filtering and masking: <https://langfuse.com/docs/observability/sdk/advanced-features>
- OpenTelemetry Collector telemetry transformations: <https://opentelemetry.io/docs/collector/transforming-telemetry/>
- OpenTelemetry Collector transform processor: <https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/main/processor/transformprocessor>
- OpenTelemetry GenAI semantic conventions: <https://github.com/open-telemetry/semantic-conventions-genai>
- OpenTelemetry GenAI spans, pinned revision: <https://github.com/open-telemetry/semantic-conventions-genai/blob/46d43c8949afb53765a202e89f4534eeb75ca3fa/docs/gen-ai/gen-ai-spans.md>

## Retain the mapping reasoning

- Neutral application attributes describe work; only the destination pipeline adds Langfuse fields.
- Preserve the whole SSO workflow so a generation remains connected to source evidence.
- Inject/extract context joins services; allowlisted baggage-to-span copying makes dimensions visible.
- Prove acceptance, export and backend lookup separately; a valid YAML file proves syntax only.

**Q: Tier is visible in catch-all metadata but dashboard filters cannot use it. Must the app emit vendor names?**

<details><summary>Answer</summary>

No. Keep the neutral source, ensure it appears on the relevant spans, then copy it into the
allowlisted `langfuse.trace.metadata.tenant_tier` destination field. APM keeps its original fields.

</details>

**Q: A generation survives a filter, but its parent does not. Has the complete SSO trace been retained?**

<details><summary>Answer</summary>

No. Shared trace ID still correlates surviving records, but missing root/retriever evidence prevents
explaining the product task and stale source. Route the whole workflow through the GenAI ingress.

</details>

**Try it:** Add bounded plan values `free` and `enterprise` to the neutral schema. Predict the
field sets at both destinations before changing the transform.

<details><summary>Worked solution</summary>

Emit `app.trace.dimension.plan` on needed spans after validating the value. In the Langfuse-only
transform, copy it to `langfuse.trace.metadata.plan` when present. APM receives only the neutral
plan; Langfuse receives neutral and copied fields. Verify both destinations with a synthetic trace;
production backend validation requires credentials and is separate from this prediction.

</details>
