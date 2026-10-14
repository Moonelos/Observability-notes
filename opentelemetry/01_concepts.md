# OpenTelemetry Concepts

OpenTelemetry, usually shortened to OTel, is the vendor-neutral standard for
creating, correlating, processing, and exporting telemetry data. It gives your
application one observability vocabulary instead of one SDK per backend.

The most important mental model is this:

```text
application code and instrumented libraries
  -> OpenTelemetry API
  -> OpenTelemetry SDK providers
       resource identity
       instrumentation scopes
       samplers, processors, metric readers, log processors
       exporters
  -> OTLP or another export format
  -> OpenTelemetry Collector
       receivers -> processors -> exporters
  -> observability backends
       traces, metrics, logs, LLM observability, dashboards, alerts
```

OpenTelemetry does not replace your backend. It standardizes what your code
emits and how telemetry moves to tools such as Jaeger, Prometheus, Grafana,
Datadog, Honeycomb, Elastic, or Langfuse.

The pipeline diagram separates the request's recording state from the destination's storage. Follow the export arrows, which carry completed telemetry rather than application requests:

```mermaid
flowchart LR
    A["chat-api POST /chat instrumentation"] --> B["API calls: spans and measurements"]
    B --> S["SDK: resource, context, aggregation"]
    S --> O["OTLP export batches"]
    O --> C["Collector receiver then processors"]
    C --> T["trace backend"]
    C --> M["metrics backend"]
    C --> L["log backend"]
```

The application first describes work, the SDK records/aggregates it, and the Collector routes exported batches. Backend storage is the final boundary. A request succeeding does not prove every arrow succeeded; this distinction makes the later accepted/sent/canary checks necessary.

## 📌 What OpenTelemetry Is Not

It is important to be precise:

- OpenTelemetry is not a tracing database like Jaeger.
- OpenTelemetry is not a metrics database like Prometheus.
- OpenTelemetry is not a dashboarding product like Grafana.
- OpenTelemetry is not a log search product.
- OpenTelemetry is not an LLM observability product like Langfuse.
- OpenTelemetry is not only a protocol.
- OpenTelemetry is not only auto-instrumentation.

OpenTelemetry is a standard plus implementations:

| Part | What it means |
| --- | --- |
| Specification | Cross-language rules for APIs, SDKs, data models, context propagation, exporters, and behavior. |
| APIs | Interfaces your code and libraries call to create spans, metrics, logs, context, and baggage. |
| SDKs | Runtime implementations that sample, aggregate, process, batch, and export telemetry. |
| Semantic conventions | Standard names for attributes, metrics, spans, resources, and common operations. |
| OTLP | OpenTelemetry Protocol, the native transport format for OTel telemetry. |
| Collector | A vendor-neutral telemetry proxy that receives, processes, routes, and exports data. |
| Instrumentation libraries | Packages that automatically instrument frameworks and clients such as FastAPI, HTTPX, SQLAlchemy, Redis, Celery, and LLM SDKs. |

The reason this is powerful is separation of concerns. Application code should
describe what happened. Pipeline configuration should decide where that data
goes. Backends should store, query, visualize, and alert on it.

## 🧭 The Problem OTel Solves

Without OTel, observability often looks like this:

```text
service code
  -> vendor A tracing SDK
  -> vendor B metrics SDK
  -> custom log format
  -> framework-specific propagation
  -> backend-specific dashboards and alerts
```

Changing vendors, adding a second backend, or sharing instrumentation between
teams becomes painful because observability concerns leak into product code.

With OTel, the shape becomes:

```text
service code
  -> OpenTelemetry API and instrumentation
  -> OpenTelemetry SDK
  -> OTLP
  -> Collector
  -> one or more backends
```

That gives you:

- one way to create traces, metrics, and logs;
- one context propagation model across services;
- one naming scheme for common attributes;
- one transport protocol for telemetry;
- one pipeline layer where you can batch, redact, sample, transform, and route;
- freedom to change or add backends without rewriting application code.

## 🔄 The End-To-End Lifecycle

A concrete request makes the architecture easier to understand. Imagine a
FastAPI `chat-api` service receives `POST /chat`, calls a retrieval service,
calls an LLM provider, writes logs, and records token metrics.

```text
client
  -> chat-api POST /chat
       server span: POST /chat
       manual span: rag.retrieve
       client span: POST retrieval /search
         -> retrieval service
              server span: POST /search
              manual span: vector_db.query
       manual span: prompt.build
       client span: chat gpt-4o-mini
       metrics: llm.requests, llm.tokens, llm.request.duration
       logs: "retrieval returned 5 docs", "model call timed out"
  -> response
```

Here is what OTel does along the way:

1. The HTTP server instrumentation sees the incoming request and starts a
   `SERVER` span.
2. The propagator extracts trace headers if the caller sent them. If no trace
   exists, this service starts a new root trace.
3. The active span is stored in the current execution context, so code deeper
   in the call stack can create child spans without passing IDs manually.
4. Manual instrumentation creates spans around business operations that the
   framework cannot understand, such as `rag.retrieve` or `prompt.build`.
5. HTTP client instrumentation creates outbound `CLIENT` spans and injects the
   current trace context into request headers.
6. The downstream service extracts those headers and creates spans with the
   same `trace_id`, so the backend can assemble one distributed trace.
7. Metrics are recorded as measurements with low-cardinality attributes such as
   route, model, provider, and outcome.
8. Logs created while a span is active can include the current `trace_id` and
   `span_id`, which lets a backend link log lines to the trace.
9. When spans end, the SDK passes them through processors, usually a batch
   processor, and exports them over OTLP.
10. The Collector receives telemetry, applies shared policy such as batching,
    memory limits, redaction, enrichment, sampling, and routing.
11. Backends store and visualize the data. Metrics usually drive alerts,
    traces explain example requests, and logs provide local details.

The glue is not magic. It is mainly:

- a shared trace context: `trace_id`, `span_id`, parent relationship, sampled flag;
- a resource identity: `service.name`, service version, environment, instance;
- instrumentation scopes: which library or module emitted the telemetry;
- semantic conventions: common attribute names such as `http.route` or `gen_ai.request.model`;
- propagation fields carried in request or message metadata: usually W3C
  `traceparent`, `tracestate`, and `baggage`;
- SDK and Collector pipelines that export the data consistently.

## 📦 The Six Layers

Every OpenTelemetry setup has the same conceptual layers, even if a small local
demo collapses some of them.

| Layer | Owns | Example |
| --- | --- | --- |
| Application work | The actual operation users care about. | Handle `/chat`, query vector DB, call model. |
| Instrumentation | Creates telemetry from that work. | Auto FastAPI span, manual `rag.retrieve` span, token counter. |
| SDK | Runtime behavior inside the process. | Providers, resources, samplers, processors, metric readers, exporters. |
| Transport | How telemetry leaves the process. | OTLP/HTTP to `http://otel-collector:4318/v1/traces`. |
| Collector pipeline | Shared telemetry infrastructure. | Receive OTLP, batch, redact, tail sample, export to multiple backends. |
| Backend | Storage, query, dashboards, alerts, workflows. | Prometheus metrics, Jaeger traces, Langfuse LLM traces. |

When notes or docs say "configure OpenTelemetry", ask which layer they mean.
Many confusions come from mixing these layers together.

## 📡 Signals

OpenTelemetry supports multiple signals. For application observability, the
main three are traces, metrics, and logs. Baggage is context that can travel
with those signals. Profiles are also part of the OTel ecosystem, but these
notes focus on traces, metrics, logs, and baggage because they are the core
signals used by most services and LLM applications today.

### Traces

A trace describes one execution path through a system. It answers:

```text
What happened to this specific request?
Where did time go?
Which downstream call failed?
Which services participated?
What was the parent-child order of operations?
```

A trace is made of spans that share a `trace_id`.

```text
trace_id: 9f4...

POST /chat                         SERVER span in chat-api
  rag.retrieve                     INTERNAL span in chat-api
    POST retrieval /search         CLIENT span in chat-api
      POST /search                 SERVER span in retrieval service
        vector_db.query            CLIENT or INTERNAL span
  prompt.build                     INTERNAL span
  chat gpt-4o-mini                 CLIENT span to model provider
```

A span represents one operation or unit of work. Important span fields are:

| Field | Meaning |
| --- | --- |
| `trace_id` | Identifier shared by all spans in the same trace. |
| `span_id` | Identifier for this span. |
| `parent_span_id` | The caller span. Empty for a root span. |
| `name` | Low-cardinality operation name, for example `POST /chat` or `rag.retrieve`. |
| `kind` | Role of the span: `SERVER`, `CLIENT`, `INTERNAL`, `PRODUCER`, or `CONSUMER`. |
| timestamps | Start time, end time, and duration. |
| attributes | Key-value metadata such as route, model, DB system, outcome. |
| span events | Timestamped records embedded in the span. OTel has announced gradual recording-API deprecation; existing data and APIs remain supported during the transition. Prefer correlated log-based events in new instrumentation. |
| links | References to related spans that are not parent-child. Useful for queues and batch work. |
| status | Whether the operation ended in error. |

Span names should be stable and low-cardinality:

| Good | Bad |
| --- | --- |
| `GET /users/{id}` | `GET /users/123456` |
| `rag.retrieve` | `retrieve query "how do refunds work"` |
| `chat gpt-4o-mini` | `chat user@example.com gpt-4o-mini` |

Put variable detail in attributes only when it is safe and bounded. Avoid raw
prompts, emails, full URLs, request bodies, document content, and user-provided
strings in general-purpose span attributes.

#### Span Kind

Span kind describes the role of the operation:

| Kind | Use for |
| --- | --- |
| `SERVER` | Receiving a request from another process, such as an HTTP endpoint. |
| `CLIENT` | Calling another process, such as HTTP, DB, Redis, vector DB, or LLM provider. |
| `INTERNAL` | Work inside the current process, such as prompt building or reranking. |
| `PRODUCER` | Publishing a message to a queue or stream. |
| `CONSUMER` | Receiving or processing a message from a queue or stream. |

Span kind helps trace backends understand the boundary between services. For an
HTTP call, the caller usually has a `CLIENT` span and the callee usually has a
`SERVER` span. They share a trace ID, but each service owns its own span.

#### Span Attributes, Log-Based Events, And Links

Use attributes for searchable facts about the operation:

```text
http.request.method = POST
http.route = /chat
http.response.status_code = 200
gen_ai.provider.name = openai
gen_ai.request.model = gpt-4o-mini
rag.retrieval.strategy = hybrid
rag.top_k = 5
```

OpenTelemetry is [deprecating the Span Event API](https://opentelemetry.io/blog/2026/deprecating-span-events/). Existing span events remain valid in OTLP and backends may continue to render them on span timelines, but new instrumentation should not call `Span.add_event()` or `Span.record_exception()`.

Use a **log-based event** for a named occurrence that needs its own timestamp. It is a `LogRecord` with a non-empty `event_name`; when emitted inside an active span, its trace and span IDs preserve correlation:

```text
LogRecord event_name: app.provider.retry.scheduled
  trace_id = 4bf9...
  span_id = 7e31...
  retry.attempt = 2
  retry.delay_ms = 250

LogRecord event_name: app.provider.request.exception
  trace_id = 4bf9...
  span_id = 7e31...
  exception.type = TimeoutError
  exception.message = request timed out
```

Use an ordinary log record when the message is diagnostic but does not define a stable event schema. Use a span attribute when the value describes the operation as a whole and does not need its own timestamp.

#### Why new events belong in the logs pipeline

Checked 2026-10-14. OpenTelemetry's [March 2026 announcement](https://opentelemetry.io/blog/2026/deprecating-span-events/)
recommends the Logs API for new events and exceptions, with a gradual deprecation
plan for `Span.AddEvent` and `Span.RecordException`. This is a transition, not removal
of existing span-event data. The [current tracing specification](https://opentelemetry.io/docs/specs/otel/trace/api/#add-events)
still defines `AddEvent`; inspect your language SDK's actual release behavior.
Separately, [exception-on-span conventions](https://opentelemetry.io/docs/specs/semconv/exceptions/exceptions-spans/)
are explicitly deprecated in favor of [exceptions on logs](https://opentelemetry.io/docs/specs/semconv/exceptions/exceptions-logs/).

Choose a representation from what happened during the same `/chat` request:

| Fact | Representation | Reason |
| --- | --- | --- |
| A model call took 700 ms | Span | An operation with a duration and boundary. |
| The requested model was `demo-model` | Span attribute | A property of the whole call. |
| Retry attempt 2 was scheduled at a particular instant | Named log-based event | A timestamped occurrence that may repeat. |
| A diagnostic message needs no stable event schema | Ordinary log | Human-readable local detail. |

A named OTel event is a `LogRecord` with a non-empty top-level `event_name`;
the [general event conventions](https://opentelemetry.io/docs/specs/semconv/general/events/)
are still Development. A JSON key named `event_name` needs a bridge or ingest mapping
to become that OTel field. Keep the active trace and span context on the record.

Follow a retry event's route separately from its model span:

```mermaid
flowchart LR
    M["active chat demo-model span"] --> E["named retry log: same trace_id and span_id"]
    M --> T["traces exporter → APM and GenAI destination"]
    E --> L["logs exporter or mapped log agent → log backend"]
    L --> C["correlate to model span using IDs"]
    T --> C
```

Correlation connects these records but does not transport them together. A traces-only
Langfuse exporter does not deliver a new log event; configure a logs destination and
verify its trace links. Moving an exception to logs also does not set the span's error
status: keep status and bounded `error.type` on the failing operation.

Embedded span events disappear when their span is dropped. Logs use an independent
pipeline, so a log can survive trace sampling and point to a trace that was never
stored. That is expected; it does not prove broken context. Apply log retention,
redaction, and volume policy separately. A named exception can carry sensitive details
just as an ordinary exception log can.

For migration, first establish working log export/correlation, then enable log-only
exceptions where the installed instrumentation supports
`OTEL_SEMCONV_EXCEPTION_SIGNAL_OPT_IN=logs`. `logs/dup` is a temporary comparison mode,
not a permanent default. Confirm exported signals and backend views; do not assume
every instrumentation honors the variable or implements a log-to-span-event compatibility
layer. [Python log setup](02_python_instrumentation.md#-optional-otel-log-export)
contains the named-event bridge. The [local destination canary](../examples/local/genai_destination_filter.py)
also verifies a named retry log correlated with a model span, without creating a span event.

<details>
<summary>Check yourself: a retry event reaches the log backend but the trace is absent. Should you create another span for the event?</summary>

No. First check whether trace sampling or destination filtering discarded the span.
Logs and traces export independently. The retry remains a point-in-time event, and
creating another span would not repair the original retention decision. Verify the
log's IDs and both pipelines' delivery policies before diagnosing context loss.

</details>

Use links when there is a relationship but not a direct parent-child hierarchy.
For example, a batch job that processes 100 messages may link to the producing
spans rather than pretending one message is the parent of the whole batch.

#### Complete Worked Trace

The field list becomes easier to understand when every field belongs to one
request. This teaching example deliberately includes:

- a successful HTTP request with a failed child operation;
- nested internal and client spans;
- attributes, span status, and correlated log-based events;
- a queue producer and a consumer in a new trace;
- a span link between the two traces;
- resource and instrumentation-scope metadata.

The application accepts a chat request, retrieves context, calls an LLM twice,
handles the provider failure, publishes an asynchronous result, and later
persists that result:

```text
Trace A: 4bf92f3577b34da6a3ce929d0e0e4736

POST /chat                                      SERVER    2.850 s  UNSET
├── rag.retrieve                                INTERNAL  0.320 s  UNSET
│   └── POST /vector-search                     CLIENT    0.280 s  UNSET
├── chat claude-sonnet                          CLIENT    2.100 s  ERROR
└── send exception-analysis-results             PRODUCER  0.040 s  UNSET

Trace B: 9a82a1c307ab4f18b029d712f346a015

process exception-analysis-results              CONSUMER  0.740 s  UNSET
└── INSERT analysis_result                      CLIENT    0.120 s  UNSET

process exception-analysis-results
  -- link --> send exception-analysis-results in Trace A
```

Trace A is one tree because its spans share a trace ID and use parent-child
relationships. The consumer intentionally starts Trace B as a new root. Its
link preserves the causal relationship without pretending that work performed
later by another process is nested synchronous work.

Continuing the producer trace into the consumer is also valid for many
single-message flows. A new trace plus a link is useful when the queue boundary
is also a lifecycle boundary, or when one consumer operation represents a
batch with several producing contexts. Choose one policy deliberately and
apply it consistently.

This timeline follows the producer carrier into a later worker. Look at the new root and link rather than assuming delayed work is synchronous child work:

```mermaid
sequenceDiagram
    participant H as chat-api POST /chat in Trace A
    participant P as send exception-analysis-results
    participant Q as fake queue carrier
    participant W as process exception-analysis-results in Trace B
    participant D as INSERT analysis_result
    H->>P: publish provider_failed result
    P->>Q: inject Trace A and producer span ID
    H-->>H: HTTP 202, root UNSET
    Q->>W: dequeue message-987 later
    W->>W: new root Trace B, link to producer Trace A
    W->>D: persist result as child in Trace B
```

The queue retains a serialized carrier after the producer ends. The worker extracts it for the link, then explicitly uses an empty parent context to start a different trace. Its database child inherits Trace B from the worker; the producer reference remains a link. If the worker instead uses the extracted context as parent, it continues Trace A—the policy choice changes tree membership, not the fact that work was caused by the message.

##### One Span With Every Major Field

This is a normalized teaching representation of the failed LLM span. It is not
literal OTLP JSON: OTLP uses its own protobuf/JSON encoding, and console
exporters have a language-specific debug format.

```json
{
  "identity": {
    "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
    "span_id": "7e31fbd423ab9c11",
    "parent_span_id": "00f067aa0ba902b7",
    "trace_flags": "01",
    "trace_state": ""
  },
  "name": "chat claude-sonnet",
  "kind": "CLIENT",
  "start_time": "2026-07-23T10:15:30.500Z",
  "end_time": "2026-07-23T10:15:32.600Z",
  "duration_ms": 2100,
  "status": {
    "code": "ERROR",
    "description": "Bedrock failed after retries"
  },
  "attributes": {
    "gen_ai.operation.name": "chat",
    "gen_ai.provider.name": "aws.bedrock",
    "gen_ai.request.model": "claude-sonnet",
    "server.address": "bedrock-runtime.us-east-1.amazonaws.com",
    "retry.count": 1,
    "app.outcome": "provider_failed",
    "error.type": "ProviderTimeoutError"
  },
  "links": [],
  "dropped_attributes_count": 0,
  "dropped_links_count": 0,
  "resource": {
    "service.name": "chat-api",
    "service.version": "1.0.0",
    "deployment.environment.name": "development"
  },
  "instrumentation_scope": {
    "name": "example.complete-trace",
    "version": "1.0.0"
  }
}
```

The retry and exception timeline is exported through the logs signal rather than embedded in the span. This is also a normalized teaching representation:

```json
[
  {
    "event_name": "app.provider.retry.scheduled",
    "timestamp": "2026-07-23T10:15:31.300Z",
    "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
    "span_id": "7e31fbd423ab9c11",
    "severity_text": "INFO",
    "attributes": {
      "retry.next_attempt": 2,
      "retry.delay_ms": 200,
      "retry.reason": "provider_timeout"
    }
  },
  {
    "event_name": "app.provider.request.exception",
    "timestamp": "2026-07-23T10:15:32.590Z",
    "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
    "span_id": "7e31fbd423ab9c11",
    "severity_text": "ERROR",
    "attributes": {
      "exception.type": "ProviderTimeoutError",
      "exception.message": "Bedrock request timed out on attempt 2",
      "exception.stacktrace": "Traceback (most recent call last): ..."
    }
  }
]
```

Read it in layers:

| Layer | Fields | Meaning |
| --- | --- | --- |
| Identity and position | `trace_id`, `span_id`, `parent_span_id`, trace flags and state | Which trace this operation belongs to, where it sits in the tree, and propagation/sampling state. |
| Operation | `name`, `kind` | What happened and whether this process acted as server, client, internal code, producer, or consumer. |
| Time | Start and end timestamps | The measured interval. Duration is normally derived from these timestamps rather than assigned by application code. |
| Description | Attributes | Searchable facts about the operation as a whole. |
| Timeline | Correlated log-based events | Named, timestamped facts emitted through the logs signal with the span's trace context. |
| Non-tree relationships | Links | Causal references that do not imply a parent-child interval. |
| Outcome | Status | Whether this operation failed. The correlated exception log explains the failure; status classifies the final outcome. |
| Emitter identity | Resource and instrumentation scope | Which service emitted the span and which code created it. |
| Data loss | Dropped counts | Whether SDK limits discarded span attributes or links. Log records have their own attribute limits and dropped count. |

The LLM child is `ERROR`, but the root HTTP span remains `UNSET` and records
`http.response.status_code=202`. That is correct here: the application handled
the provider failure and successfully accepted asynchronous work. A parent's
status describes the parent operation, not the worst status among its children.

> 💡 **Key insight:** A parent span's status reflects its own outcome, not the worst status of any child — a request that gracefully handles a failed provider call and returns 202 should remain UNSET, not inherit the child's ERROR.

The consumer span has a different trace ID and no parent, but contains this
relationship:

```json
{
  "name": "process exception-analysis-results",
  "trace_id": "9a82a1c307ab4f18b029d712f346a015",
  "parent_span_id": null,
  "links": [
    {
      "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
      "span_id": "ae32b4f11d98c307",
      "attributes": {
        "link.type": "produced_by",
        "messaging.message.id": "message-987"
      }
    }
  ]
}
```

##### Runnable Python Simulation

This is a single-process simulation, not a substitute for FastAPI, HTTP client,
SQS, LLM, and database instrumentations. It keeps the infrastructure fake so
the span mechanics remain visible. It uses `SimpleSpanProcessor` only to make
console output deterministic for a short-lived demo; production services
normally use `BatchSpanProcessor` and OTLP.

This simulation verifies the trace side and intentionally does not configure a
logs provider. The correlated `LogRecord` implementation shown above is built
with structlog in [Python Instrumentation](02_python_instrumentation.md#emit-named-log-based-events-through-structlog).

Use Python 3.11 or later:

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install \
  'opentelemetry-api>=1.39,<2' \
  'opentelemetry-sdk>=1.39,<2'
```

Save the following as `complete_trace_demo.py` and run
`python complete_trace_demo.py`:

```python
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any

from opentelemetry import context as otel_context
from opentelemetry import propagate, trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    ConsoleSpanExporter,
    SimpleSpanProcessor,
)
from opentelemetry.trace import Link, SpanKind, Status, StatusCode


resource = Resource.create(
    {
        "service.name": "chat-api",
        "service.version": "1.0.0",
        "deployment.environment.name": "development",
    }
)
provider = TracerProvider(resource=resource)
provider.add_span_processor(
    SimpleSpanProcessor(ConsoleSpanExporter())
)
trace.set_tracer_provider(provider)
tracer = trace.get_tracer("example.complete-trace", "1.0.0")


class ProviderTimeoutError(TimeoutError):
    pass


@dataclass(frozen=True)
class QueueMessage:
    message_id: str
    job_id: str
    body: dict[str, Any]
    carrier: dict[str, str]


def fake_vector_search(query: str) -> list[dict[str, Any]]:
    time.sleep(0.01)
    return [
        {"id": f"doc-{index}", "score": 0.9 - index * 0.05}
        for index in range(1, 6)
    ]


def fake_llm_call(attempt: int) -> str:
    time.sleep(0.01)
    raise ProviderTimeoutError(
        f"Bedrock request timed out on attempt {attempt}"
    )


def retrieve_documents(query: str) -> list[dict[str, Any]]:
    with tracer.start_as_current_span(
        "rag.retrieve",
        kind=SpanKind.INTERNAL,
        attributes={
            "rag.query.length": len(query),
            "rag.top_k": 5,
            "rag.reranking.enabled": True,
        },
    ) as retrieval_span:
        with tracer.start_as_current_span(
            "POST /vector-search",
            kind=SpanKind.CLIENT,
            attributes={
                "http.request.method": "POST",
                "url.full": (
                    "https://retrieval-service/vector-search"
                ),
                "server.address": "retrieval-service",
                "server.port": 443,
            },
        ) as client_span:
            documents = fake_vector_search(query)
            client_span.set_attribute(
                "http.response.status_code", 200
            )

        retrieval_span.set_attribute("rag.documents.before_rerank", 20)
        retrieval_span.set_attribute(
            "rag.documents.after_rerank", len(documents)
        )
        retrieval_span.set_attribute(
            "rag.reranker.model", "cohere-rerank-v3"
        )
        retrieval_span.set_attribute(
            "rag.documents.returned", len(documents)
        )
        retrieval_span.set_attribute("app.outcome", "success")
        return documents


def call_llm_with_retry(prompt: str) -> str | None:
    with tracer.start_as_current_span(
        "chat claude-sonnet",
        kind=SpanKind.CLIENT,
        attributes={
            "gen_ai.operation.name": "chat",
            "gen_ai.provider.name": "aws.bedrock",
            "gen_ai.request.model": "claude-sonnet",
            "server.address": (
                "bedrock-runtime.us-east-1.amazonaws.com"
            ),
            "app.prompt.length": len(prompt),
        },
    ) as span:
        for attempt in (1, 2):
            span.set_attribute("retry.current_attempt", attempt)
            try:
                return fake_llm_call(attempt)
            except ProviderTimeoutError as exc:
                if attempt == 1:
                    span.set_attribute("retry.next_attempt", 2)
                    span.set_attribute("retry.delay_ms", 5)
                    span.set_attribute(
                        "retry.reason", "provider_timeout"
                    )
                    time.sleep(0.005)
                    continue

                # The exception is handled here, so the span must receive
                # explicit failure semantics. Send the stack trace through
                # the correlated logs pipeline, not as a span event.
                span.set_attribute("retry.count", attempt - 1)
                span.set_attribute(
                    "app.outcome", "provider_failed"
                )
                span.set_attribute(
                    "error.type", type(exc).__qualname__
                )
                span.set_status(
                    Status(
                        StatusCode.ERROR,
                        description="Bedrock failed after retries",
                    )
                )
                return None

    raise AssertionError("unreachable")


def publish_result(
    *, job_id: str, result: dict[str, Any]
) -> QueueMessage:
    message_id = str(uuid.uuid4())

    with tracer.start_as_current_span(
        "send exception-analysis-results",
        kind=SpanKind.PRODUCER,
        attributes={
            "messaging.system": "aws_sqs",
            "messaging.destination.name": (
                "exception-analysis-results"
            ),
            "messaging.operation.name": "send",
            "messaging.operation.type": "send",
            "messaging.message.id": message_id,
            "app.job.id": job_id,
        },
    ) as span:
        time.sleep(0.005)
        carrier: dict[str, str] = {}
        # Serialization only: the application still has to transport this
        # carrier with the message.
        propagate.inject(carrier)
        span.set_attribute(
            "messaging.message.body.size",
            len(str(result).encode()),
        )

    return QueueMessage(
        message_id=message_id,
        job_id=job_id,
        body=result,
        carrier=carrier,
    )


def persist_result(result: dict[str, Any]) -> None:
    with tracer.start_as_current_span(
        "INSERT analysis_result",
        kind=SpanKind.CLIENT,
        attributes={
            "db.system.name": "postgresql",
            "db.namespace": "exception_management",
            "db.operation.name": "INSERT",
            "db.collection.name": "analysis_result",
            "server.address": "results-db.internal",
            "server.port": 5432,
        },
    ):
        time.sleep(0.005)


def consume_message(message: QueueMessage) -> None:
    extracted = propagate.extract(message.carrier)
    producer_context = trace.get_current_span(
        extracted
    ).get_span_context()
    producer_link = Link(
        producer_context,
        attributes={
            "link.type": "produced_by",
            "messaging.message.id": message.message_id,
        },
    )

    # An empty Context prevents the producer from becoming the parent.
    with tracer.start_as_current_span(
        "process exception-analysis-results",
        context=otel_context.Context(),
        kind=SpanKind.CONSUMER,
        links=[producer_link],
        attributes={
            "messaging.system": "aws_sqs",
            "messaging.destination.name": (
                "exception-analysis-results"
            ),
            "messaging.operation.name": "process",
            "messaging.operation.type": "process",
            "messaging.message.id": message.message_id,
            "app.job.id": message.job_id,
        },
    ) as span:
        span.set_attribute("messaging.message.delivery_count", 1)
        persist_result(message.body)


def handle_chat_request(query: str) -> QueueMessage:
    job_id = str(uuid.uuid4())
    with tracer.start_as_current_span(
        "POST /chat",
        kind=SpanKind.SERVER,
        attributes={
            "http.request.method": "POST",
            "http.route": "/chat",
            "url.path": "/chat",
            "url.scheme": "https",
            "server.address": "chat-api",
        },
    ) as root_span:
        root_span.set_attribute(
            "app.validation.schema", "chat-request-v2"
        )
        documents = retrieve_documents(query)
        answer = call_llm_with_retry(
            f"{query}\n\nRetrieved document count: {len(documents)}"
        )

        if answer is None:
            result: dict[str, Any] = {
                "status": "provider_failed",
                "answer": None,
            }
            root_span.set_attribute(
                "app.fallback.action", "publish_failure_result"
            )
        else:
            result = {"status": "completed", "answer": answer}

        message = publish_result(job_id=job_id, result=result)
        root_span.set_attribute("http.response.status_code", 202)
        root_span.set_attribute("app.job.id", job_id)
        root_span.set_attribute("app.response.mode", "async")
        return message


def main() -> None:
    message = handle_chat_request(
        "How does OpenTelemetry tracing work?"
    )
    time.sleep(0.01)
    consume_message(message)
    provider.shutdown()


if __name__ == "__main__":
    main()
```

The console output will use generated IDs and actual measured timestamps, so it
will not match the illustrative IDs above. Verify these invariants instead:

- the first five spans share one trace ID and follow the shown parent IDs;
- every span has its own span ID;
- the LLM span has `error.type`, retry attributes, and `ERROR` status;
- the root span remains `UNSET` with HTTP status `202`;
- the consumer has a new trace ID, no parent, and one link to the producer;
- the database span is a child of the consumer;
- every span carries the simulation's `chat-api` resource; in a real
  deployment, the worker would normally have its own service resource;
- `get_tracer()` attaches the `example.complete-trace` instrumentation scope,
  although some console-exporter versions omit it from their debug rendering.

The SDK generates IDs, captures start and end times, calculates parentage from
the active context, and tracks limit-related dropped counts. Instrumentation
chooses the operation name and kind and adds domain attributes.
Provider setup supplies the resource; `get_tracer()` supplies the
instrumentation scope. Status can be explicit, or the Python context manager
can set `ERROR` for an escaping exception. Its default exception recording
still creates a legacy span event, so new instrumentation should pass
`record_exception=False` when exceptions may escape and emit the exception
through the correlated logs pipeline. If code catches an exception inside the
span, as this demo does for retry handling, set the final status and
low-cardinality `error.type` explicitly.

In a real service, let each instrumentation own only the protocol semantics you
actually want. FastAPI/ASGI can own inbound HTTP spans, HTTPX instrumentation
outbound calls, and database instrumentation client spans. FastAPI
instrumentation does not also instrument an SQS or Kafka boundary; messaging
behavior comes from a separate queue instrumentation package.

For queues, first choose between continuing the producer trace and starting a
new trace with a link. If the queue instrumentation emits that exact topology,
let it own injection, extraction, and consumer spans. If it does not, disable
that queue instrumentor in the worker and own the boundary manually, as this
simulation does. Starting an empty-context span inside an already automatic
consumer span changes only the new span's parent; it does not erase the
automatic span that was already exported. See
[Python Instrumentation](02_python_instrumentation.md) for the concrete worker
policy and selective-instrumentation examples.

Keep manual spans for business operations such as `rag.retrieve`. Export with
OTLP through a batch processor, and never put raw prompts, retrieved documents,
queue payloads, credentials, or personal data into general-purpose attributes.
The GenAI and messaging conventions evolve faster than core tracing, so pin
the convention version used by instrumentation packages and recheck these
names during upgrades.

### Metrics

Metrics are numerical measurements aggregated over time. They answer:

```text
How is the system behaving in aggregate?
Is latency above the SLO?
Did the error rate spike?
How many tokens are we using per model?
How deep is the queue?
```

Metrics are not "compressed traces". They are their own signal and should be
emitted independently. This matters because traces are often sampled, while
unsampled metrics are the appropriate aggregate signal for dashboards,
autoscaling, request/error rates, and alerts.

"Unsampled" does not mean an accounting ledger. Exporter loss, queue overflow,
process crashes or restarts, cumulative/delta temporality conversion, Collector
failure, and backend rejection can all lose or reset measurements. Use a
transactional billing or audit system for exact money, quota, and compliance
records; use telemetry metrics to operate the system.

OpenTelemetry metrics have a few moving parts:

```text
MeterProvider
  -> Meter
       -> instrument
            -> measurement + attributes
                 -> SDK aggregation
                      -> metric reader
                           -> exporter
```

Do not collapse the instrument, metric stream, and data point into one object.
The instrument is the API object that records measurements. The SDK aggregates
those measurements into a metric stream, and OTLP exports data points from that
stream. In the
[OTel metrics data model](https://opentelemetry.io/docs/specs/otel/metrics/data-model/),
a metric stream contains more than attributes:

| Part | Typical fields | What it tells the backend |
| --- | --- | --- |
| Identity | Resource, instrumentation scope, `name`, `description`, `unit` | Who emitted the metric and what the measurement means. |
| Aggregation contract | Data type plus, where applicable, temporality and monotonicity | Whether values are a gauge, sum, histogram, delta, or cumulative total. |
| Data points | Timestamp or time window plus the numeric payload | The actual value or aggregate for one collection interval. |
| Attributes | A key-value set on each data point | The dimensions that identify an individual time series within the metric stream. |
| Correlation and state | Optional exemplars and data-point flags | A sampled link to trace context, or an explicit marker such as "no recorded value". |

The numeric payload depends on the data type. A `Gauge` point carries the last
sampled value. A `Sum` point carries a value over a delta or cumulative time
window and the stream says whether the sum is monotonic. A `Histogram` point
compresses many measurements into `count`, `sum`, and optional buckets,
`min`, and `max`.

Here is one normalized teaching representation of an exported histogram. It is
not literal OTLP JSON; real OTLP nests the same information under
`ResourceMetrics` and `ScopeMetrics`, represents timestamps in Unix
nanoseconds, and uses protocol field names:

```json
{
  "resource": {
    "service.name": "chat-api",
    "service.instance.id": "chat-api-7d9f"
  },
  "scope": {
    "name": "opentelemetry.instrumentation.fastapi",
    "version": "0.65b0"
  },
  "metric": {
    "name": "http.server.request.duration",
    "description": "Duration of HTTP server requests.",
    "unit": "s",
    "data": {
      "type": "Histogram",
      "aggregation_temporality": "DELTA",
      "data_points": [
        {
          "start_time": "2026-08-09T10:15:20Z",
          "time": "2026-08-09T10:15:30Z",
          "attributes": {
            "http.request.method": "POST",
            "http.route": "/chat",
            "http.response.status_code": 200,
            "url.scheme": "https"
          },
          "count": 4,
          "sum": 1.42,
          "min": 0.20,
          "max": 0.62,
          "explicit_bounds": [0.10, 0.25, 0.50, 1.00],
          "bucket_counts": [0, 2, 1, 1, 0],
          "exemplars": [
            {
              "time": "2026-08-09T10:15:28.420Z",
              "value": 0.62,
              "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
              "span_id": "7e31fbd423ab9c11",
              "filtered_attributes": {}
            }
          ]
        }
      ]
    }
  }
}
```

Read this point as: during the ten-second delta window, this service observed
four successful `POST /chat` requests with a total duration of `1.42 s`. There
are five bucket counts because four explicit boundaries create five ranges;
the counts add up to `count`. The `0.62 s` exemplar is already included in the
histogram aggregates and gives the backend one representative trace to open.
It does not make `trace_id` a metric attribute.

The boundaries above are deliberately shortened to make the structure visible.
For the actual `http.server.request.duration` instrument, follow its
[semantic convention](https://opentelemetry.io/docs/specs/semconv/http/http-metrics/#metric-httpserverrequestduration)
and use SDK Views when different buckets are justified by the SLO. An absent
exemplar does not mean the metric failed: exemplar sampling, trace sampling,
SDK support, and backend support all affect whether one is available.

Each exact attribute set produces a separate time series. A second point with
`http.response.status_code=500`, for example, is not another field on this
series; it belongs to a different series under the same metric stream. This is
why request IDs, trace IDs, user IDs, and raw URLs must not be metric
attributes.

Common instruments:

| Instrument | Meaning | Example |
| --- | --- | --- |
| Counter | Monotonic total that only increases. | Requests, errors, tokens, jobs completed. |
| UpDownCounter | Value that can increase or decrease through add operations. | In-flight requests, active sessions. |
| Histogram | Distribution of recorded values. | Request duration, token count, document count. |
| ObservableGauge | Current value observed by callback. | Queue depth, cache size, open connections. |

Metric attributes become dimensions. Keep them low-cardinality:

| Good attribute | Why |
| --- | --- |
| `http.route="/chat"` | Bounded route template. |
| `http.response.status_code=500` | Small set of status codes. |
| `gen_ai.request.model="gpt-4o-mini"` | Bounded model list. |
| `app.outcome="error"` | Small outcome enum. |
| `app.tenant.tier="enterprise"` | Small business category. |

Avoid high-cardinality metric attributes:

| Bad attribute | Why |
| --- | --- |
| `user.email` | Personal data and unbounded values. |
| `trace_id` | Unique per trace, explodes time series. |
| `url.full` | Often contains IDs and query strings. |
| `prompt` | Sensitive, huge, and unbounded. |
| `exception.message` | Often unique per error. |

Use metrics for detection. Use traces for investigation. During an incident,
the usual flow is:

```text
metric alert fires
  -> dashboard shows route/model/provider affected
  -> trace query finds example slow/error requests
  -> logs explain local details
```

### Logs

Logs are timestamped records. They answer:

```text
What did the code say at this moment?
What local values or messages were recorded?
What stack trace was produced?
```

OpenTelemetry can do two useful things for logs:

1. It can normalize logs into the OTel log data model and export them through
   an OTel pipeline.
2. It can correlate logs with traces by adding `trace_id` and `span_id` to log
   records created while a span is active.

In Python, full OTel log export support is still marked Development in the
official language status, while the logs signal itself is stable in the OTel
specification. In practice, Python teams often start with normal structured
logging plus trace-log correlation, then decide later whether to export logs
through OTel.

Use structured logs in production:

```json
{
  "timestamp": "2026-06-18T10:15:23Z",
  "level": "INFO",
  "message": "retrieval completed",
  "service.name": "chat-api",
  "trace_id": "9f4...",
  "span_id": "1a2...",
  "rag.returned_documents": 5
}
```

Use named log records for point-in-time events, whether they are meaningful only
inside one trace or need to be queried independently. Set `event_name` for a
stable event schema; leave it empty for ordinary diagnostic logs. Emitting the
record while a span is active supplies trace correlation without embedding the
record in the span payload.

Correlation is an identifier match, not a retention guarantee. A log can carry
valid `trace_id` and `span_id` values even when sampling or backend retention
later removes the corresponding trace. A log backend can therefore contain a
correlated record for which the trace backend has no stored trace.

### Baggage

Baggage is key-value context that propagates with a request across service
boundaries via the W3C `baggage` HTTP header (alongside `traceparent` and
`tracestate`). It answers:

```text
What small, request-level facts should all downstream services be able to see?
```

Examples:

```text
app.tenant.tier = enterprise
app.experiment.variant = reranker_b
app.session.id = opaque-session-id
app.request.class = interactive
```

Baggage travels the entire downstream chain, not just the immediate next hop.
Every service that receives the request can read it.

Baggage is not the same as span attributes:

| | Baggage | Span attribute |
| --- | --- | --- |
| Travels downstream | Yes, to all services in the chain | No, stays in the current span |
| Appears in traces automatically | No | Yes |
| Use when | Downstream services need the value | Only the current service needs it |

Baggage does not appear in a trace, metric, or log unless you explicitly copy
selected keys. To attach a baggage value to the current span:

```python
from opentelemetry import baggage, trace

tenant_tier = baggage.get_baggage("app.tenant.tier")
if tenant_tier:
    trace.get_current_span().set_attribute("app.tenant.tier", tenant_tier)
```

Security rule: baggage is sent across service boundaries and is readable by
every service in the chain. Do not put secrets, API keys, emails, raw prompts,
retrieved documents, access tokens, or personal data in baggage. Treat incoming
baggage as untrusted unless you control the caller.

> ⚠️ **Watch out:** Baggage is forwarded to every downstream service in the call chain — never put secrets, tokens, emails, or prompts in it, and treat baggage arriving from untrusted callers as potentially adversarial.

## 🔌 API, SDK, And Instrumentation

OpenTelemetry separates the API from the SDK.

The API is what instrumentation code calls:

```python
from opentelemetry import trace

tracer = trace.get_tracer(__name__)


def rerank_documents(query: str, documents: list[str]) -> list[str]:
    with tracer.start_as_current_span("rag.rerank") as span:
        span.set_attribute("rag.candidate_documents", len(documents))
        ranked = reranker.rank(query, documents)
        span.set_attribute("rag.returned_documents", len(ranked))
        return ranked
```

The SDK is what the application configures once at startup:

```python
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

resource = Resource.create(
    {
        "service.name": "chat-api",
        "service.version": "2026.06.18",
        "deployment.environment.name": "production",
    }
)

provider = TracerProvider(resource=resource)
provider.add_span_processor(
    BatchSpanProcessor(
        OTLPSpanExporter(endpoint="http://otel-collector:4318/v1/traces")
    )
)
trace.set_tracer_provider(provider)
```

If no SDK is configured, API calls are no-ops. This is intentional. A library
can safely depend on `opentelemetry-api` and create spans without forcing an
exporter or backend on every application that imports it.

> 💡 **Key insight:** A shared library can add full instrumentation by depending only on opentelemetry-api — the application that configures the SDK decides where telemetry goes, with zero overhead in libraries that are imported without one.

### Providers

Providers are the SDK entry points:

| Provider | Creates | Signal |
| --- | --- | --- |
| `TracerProvider` | `Tracer` instances | Traces |
| `MeterProvider` | `Meter` instances | Metrics |
| `LoggerProvider` | OTel logger instances or bridges | Logs |

Most applications configure one provider per signal during process startup.
Avoid creating providers in random modules. Instrumentation should ask the
global provider for a tracer or meter, not create its own provider.

### Tracers, Meters, And Loggers

A tracer creates spans. A meter creates metric instruments. A logger or logging
bridge creates log records.

When you call:

```python
tracer = trace.get_tracer(__name__)
meter = metrics.get_meter(__name__)
```

the name becomes part of the instrumentation scope. It does not usually
represent the service. The service is represented by the resource.

### Instrumentation Scope

Instrumentation scope identifies the code unit that emitted telemetry. It is
usually a module, package, class, library, or instrumentation library name plus
version.

This distinction matters:

| Concept | Describes | Example |
| --- | --- | --- |
| Resource | The entity producing telemetry. | `service.name=chat-api`, `service.version=abc123`. |
| Instrumentation scope | The code that emitted telemetry. | `opentelemetry.instrumentation.fastapi`, `myapp.rag`. |
| Span attributes | Facts about one operation. | `http.route=/chat`, `rag.top_k=5`. |
| Metric attributes | Dimensions for one measurement. | `gen_ai.request.model=gpt-4o-mini`, `app.outcome=success`. |
| Baggage | Small propagated request context. | `app.tenant.tier=enterprise`. |

Do not overload one layer to do another layer's job. For example, do not put
`user.id` in a resource, because a resource describes the service instance, not
the request.

### Auto-Instrumentation And Manual Instrumentation

Auto-instrumentation creates telemetry for common framework and library work:

- inbound HTTP server spans;
- outbound HTTP client spans;
- database client spans;
- queue producer and consumer spans;
- common runtime or framework metrics;
- trace context injection and extraction;
- trace-log correlation.

This coverage is additive, not transitive. Installing FastAPI instrumentation
adds FastAPI/ASGI behavior; it does not make the framework instrument every
client, database, or queue used by a route. Each library needs its own matching
instrumentation, and each enabled instrumentation owns the span and propagation
semantics at that boundary.

Manual instrumentation fills the business gaps:

- `rag.retrieve`;
- `prompt.build`;
- `agent.plan`;
- `agent.execute_tool`;
- `guardrail.evaluate`;
- domain-specific counters and histograms.

Use both. Auto-instrumentation gives coverage. Manual instrumentation gives
meaning.

## 🏷️ Resources

A resource describes the entity that produced telemetry. Every production
service should set `service.name` explicitly.

```python
Resource.create(
    {
        "service.namespace": "support-platform",
        "service.name": "chat-api",
        "service.version": "immutable-git-sha",
        "service.instance.id": "runtime-instance-id",
        "deployment.environment.name": "production",
        "cloud.region": "us-east-1",
        "k8s.namespace.name": "prod",
    }
)
```

Good resource attributes:

- stable service namespace;
- service name;
- service version;
- deployment environment;
- service instance ID;
- host, container, pod, namespace, cluster, cloud region;
- SDK language and version, often added by the SDK.

Bad resource attributes:

- user ID;
- session ID;
- prompt text;
- request URL;
- tenant ID if there are many tenants;
- anything that changes per request.

Resources are attached to telemetry by the provider. Once a provider is created
with a resource, telemetry from tracers and meters from that provider carries
that resource.

Production identity has stricter rules than the example values suggest:

- `service.namespace` and `service.name` identify the logical service and stay
  the same across replicas.
- `service.instance.id` stays stable for one process/runtime instance and is
  different between replicas. A request ID, Lambda invocation ID, deployment
  name, or static service name is not an instance identity.
- `service.version` is the immutable artifact version, preferably the full Git
  SHA supplied by CI; do not use `latest`, a branch, or a rollout label.
- Preserve native platform identity such as `k8s.pod.uid`, `container.id`, or
  an ECS task ARN alongside service identity.
- Give each attribute one owner. Do not set conflicting values in code,
  deployment environment, and Collector enrichment.
- A gateway Collector must not stamp application telemetry with the
  Collector's own pod, container, host, or instance identity.

## 🔗 Context Propagation

Context propagation carries causal identity across process boundaries. The
receiver can use it as a parent to continue one trace or as a `Link` from a new
trace.

Inside one process, OpenTelemetry stores the active span in an execution
context. When code creates a new span, it becomes a child of the active span
unless you specify otherwise.

Across processes, that context must be serialized into a carrier such as HTTP
headers, queue message metadata, or gRPC metadata.

> **The near-miss**: `inject()` sounds like it sends context somewhere. It does
> no I/O. It only serializes the selected propagation fields into the mutable
> carrier you provide; application or library code must transport that carrier.

A **carrier** is a caller-owned mutable representation that can hold propagation
fields; the caller may be application code or an instrumentation library. With
the usual W3C propagators, those fields include `traceparent`, optional
`tracestate`, and `baggage` when the baggage propagator is configured. The
carrier is not a second OpenTelemetry network channel.

Keep propagation and telemetry export as two different network paths:

```text
application traffic
caller ── HTTP / SQS / Kafka + carrier metadata ──> callee

telemetry traffic
caller and callee ── OTLP spans / metrics / logs ──> Collector or backend
```

`traceparent` rides with the application request or message. Completed spans
are exported separately, usually through OTLP. Neither `inject()` nor
`extract()` contacts the Collector.

For HTTP, the standard trace context headers are:

```text
traceparent: 00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01
tracestate: vendor-specific-key-values
baggage: app.tenant.tier=enterprise,app.experiment.variant=reranker_b
```

The basic operation is:

```text
caller
  current span exists
  propagate.inject(carrier)
    -> serialize context into propagation fields
  application/library maps carrier to transport metadata
    -> HTTP headers, SQS MessageAttributes, Kafka headers, ...
  transport sends request or message

callee
  application/library reads transport metadata into a carrier
  propagate.extract(carrier)
    -> deserialize fields into an OTel Context
  start server span with remote parent
```

Assuming the SDK is configured, this same-process simulation makes the
serialization boundary visible:

```python
from opentelemetry import trace
from opentelemetry.propagate import extract, inject

tracer = trace.get_tracer("example.propagation")

with tracer.start_as_current_span("caller") as caller:
    outgoing_carrier: dict[str, str] = {}
    inject(outgoing_carrier)

# `inject()` mutated the dictionary; it did not send it.
assert "traceparent" in outgoing_carrier
print(sorted(outgoing_carrier))

# A dictionary copy stands in for an HTTP client, broker, or RPC library
# transporting the serialized fields to another process.
incoming_carrier = dict(outgoing_carrier)
incoming_ctx = extract(incoming_carrier)

with tracer.start_as_current_span(
    "worker.process",
    context=incoming_ctx,
) as worker:
    assert (
        worker.get_span_context().trace_id
        == caller.get_span_context().trace_id
    )
    print("continued trace:", True)
```

Expected output includes `traceparent` in the first line and
`continued trace: True` in the second. If `traceparent` is absent, there was no
valid current span or the configured propagator does not inject W3C Trace
Context.

`extract()` also performs no I/O and does not automatically attach its result as
the current context. The caller must use the returned `Context` explicitly as a
parent, attach it, or read its `SpanContext` to create a link.

The same serialized meaning uses different transport representations:

| Transport | Where the carrier travels |
| --- | --- |
| HTTP | Request headers such as `traceparent`. |
| gRPC | Call metadata. |
| Kafka | Record headers, usually through a Kafka-specific setter/getter. |
| SQS | `MessageAttributes`, through an SQS-specific setter/getter because values are nested objects rather than plain strings. |

The concrete SQS getter/setter is shown in
[Python Instrumentation](02_python_instrumentation.md).

For example, an HTTP client passes the carrier as real HTTP headers:

```python
with tracer.start_as_current_span("reserve inventory"):
    outgoing_carrier: dict[str, str] = {}
    inject(outgoing_carrier)

    response = httpx.post(
        "https://inventory.internal/reserve",
        headers=outgoing_carrier,
    )
```

Most HTTP framework/client instrumentations do this automatically. Manual
`inject()` and `extract()` are still useful for custom transports, queues,
tests, or code where you need explicit control. A transport-specific
instrumentation still follows the same model; it merely owns the carrier
adapter and the send/receive calls for you.

Broken propagation symptoms:

- every service starts a separate trace;
- traces show client spans with no matching downstream server span;
- logs contain span IDs but no shared trace ID across services;
- asynchronous jobs cannot be connected to their producer.

Common causes:

- missing HTTP client/server instrumentation;
- custom transport does not copy headers or message metadata;
- reverse proxy strips tracing headers;
- async context is lost by thread pools or background tasks;
- services use incompatible propagator configuration;
- incoming context is extracted after the server span has already been created.

## 🏷️ Semantic Conventions

Semantic conventions are standard names for common telemetry. They are why
backends can understand traces and metrics from many languages and libraries.

Examples:

| Area | Attributes |
| --- | --- |
| HTTP | `http.request.method`, `http.route`, `http.response.status_code` |
| Service/resource | `service.name`, `service.version`, `deployment.environment.name` |
| Database | `db.system.name`, `db.namespace`, `db.operation.name` |
| Messaging | `messaging.system`, `messaging.destination.name`, `messaging.operation.name` |
| GenAI | `gen_ai.operation.name`, `gen_ai.provider.name`, `gen_ai.request.model`, `gen_ai.usage.input_tokens` |

Use semantic convention names when they exist. Use your own namespace for
application-specific facts:

```text
app.tenant.tier
app.outcome
rag.retrieval.strategy
agent.tool.name
guardrail.policy.name
```

Do not invent names that conflict with official conventions. Do not use
backend-specific names in general application instrumentation unless the data is
intentionally backend-specific.

## 📤 Exporters

Exporters send telemetry out of the SDK or Collector.

Common exporter destinations:

- console/stdout for local debugging;
- OTLP endpoint, usually a Collector;
- a backend-specific endpoint;
- Prometheus pull endpoint for metrics in some setups.

OTLP is the native OpenTelemetry protocol. Common defaults:

| Transport | Port | Typical endpoint |
| --- | --- | --- |
| OTLP/gRPC | `4317` | `http://otel-collector:4317` |
| OTLP/HTTP | `4318` | `http://otel-collector:4318` |
| OTLP/HTTP traces | `4318` | `/v1/traces` |
| OTLP/HTTP metrics | `4318` | `/v1/metrics` |
| OTLP/HTTP logs | `4318` | `/v1/logs` |

In application code, prefer exporting to a Collector in production:

```text
service -> OTLP exporter -> Collector -> backends
```

Direct export to a backend is fine for local development or simple prototypes,
but production systems usually benefit from a Collector because it centralizes
routing, retries, redaction, sampling, batching, credentials, and backend
configuration.

## 🔄 Processors, Readers, And Samplers

Telemetry usually does not go straight from API call to network request. The SDK
has signal-specific components in between.

### Span Processors

Span processors receive spans from the SDK before export.

| Processor | Use |
| --- | --- |
| `BatchSpanProcessor` | Production default. Queues spans and exports them in batches. |
| `SimpleSpanProcessor` | Exports synchronously when a span ends. Useful for tests and debugging. |
| Custom span processor | Add attributes, copy baggage, filter, or integrate custom behavior. |

Use `BatchSpanProcessor` in production request paths. `SimpleSpanProcessor`
adds export latency directly to the operation ending the span.

### Metric Readers

Metric readers control how metric data is collected and exported. A common
production setup uses a periodic exporting reader:

```text
measurements recorded continuously
  -> SDK aggregates by instrument and attributes
  -> reader collects every N seconds
  -> exporter sends metric batch
```

Metrics are aggregation-first. You record measurements; the SDK turns them into
streams suitable for your exporter and backend.

### Log Processors

Log processors play the same general role for OTel log records: they receive,
process, batch, and export logs. Language support varies, so check the language
status before relying on full log export in a production design.

### Samplers

Samplers decide whether traces should be recorded and exported.

Head sampling decides early, usually when the root span starts:

```text
root span starts
  -> sampler decides sampled or not sampled
  -> a parent-based sampler makes children follow the parent decision
```

Head sampling is cheap and easy. Its limitation is that it cannot know whether
the trace will later become slow or error.

Parent-following is not universal. `ParentBased` delegates root decisions to a
configured root sampler and respects the remote/local parent's sampled flag for
children. A non-parent-based sampler can make a new decision for each span,
which can produce partial traces and usually needs a deliberate reason.

Tail sampling decides later, usually in the Collector, after seeing most or all
spans in a trace:

```text
spans arrive at Collector
  -> Collector buffers trace for a decision window
  -> policy keeps errors, slow traces, important attributes, or a percentage
```

Tail sampling is more powerful but stateful. It requires all spans for a trace
to reach the same sampling decision point.

Sampling affects traces. It should not be your only source of request counts,
error rates, or SLO metrics. Emit metrics separately.

> ⚠️ **Watch out:** Sampled traces cannot produce accurate request counts, error rates, or SLO metrics — always emit metrics independently, or your alerts will fire on noise from sampling math rather than real incidents.

## 🔀 The Collector

The OpenTelemetry Collector is a telemetry proxy. It can receive telemetry in
several formats, process it, and export it to one or more backends.

Collector configuration has pipeline components:

| Component | Direction | Example use |
| --- | --- | --- |
| Receiver | Into the Collector. | Receive OTLP over gRPC/HTTP, scrape Prometheus, read files. |
| Processor | In the middle. | Batch, memory limit, redact, transform, add resource attributes, sample. |
| Exporter | Out of the Collector. | Send OTLP to Langfuse/APM, remote write metrics, send logs. |
| Connector | Between pipelines. | Derive metrics from spans or route data between pipelines. |
| Extension | Collector capability, not direct telemetry flow. | Health check, auth, diagnostics. |

The `service.pipelines` section enables the actual pipelines. A component can
be configured but unused if it is not listed in a pipeline.

```yaml
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
    limit_mib: 512
  batch:

exporters:
  otlphttp/traces:
    endpoint: https://apm.example.com/otlp
  prometheus_remote_write:
    endpoint: https://prometheus.example.com/api/v1/write

service:
  pipelines:
    traces:
      receivers: [otlp]
      processors: [memory_limiter, batch]
      exporters: [otlphttp/traces]
    metrics:
      receivers: [otlp]
      processors: [memory_limiter, batch]
      exporters: [prometheus_remote_write]
```

Processor order matters. For example, put memory limiting early, redaction
before exporting outside your trust boundary, and batching near the end.

Common production reasons to use a Collector:

- keep backend credentials out of application services;
- change exporters without redeploying every service;
- fan out traces to multiple backends;
- send traces, metrics, and logs to different destinations;
- centralize redaction and attribute cleanup;
- add resource attributes consistently;
- tail sample traces;
- protect backends with batching, retry, and queueing;
- observe the telemetry pipeline itself.

## 🗄️ Backends

Backends are where telemetry becomes useful to humans and automation:

| Backend type | Stores | Typical use |
| --- | --- | --- |
| Trace backend | Spans and traces | Investigate individual requests and service dependencies. |
| Metrics backend | Time series | Dashboards, alerts, SLOs, autoscaling, capacity. |
| Log backend | Log records | Search local messages, stack traces, audit-style events. |
| LLM observability backend | LLM spans, prompts, outputs, scores, sessions | Prompt/version analysis, quality evaluation, cost, datasets, experiments. |

OTel does not define your dashboards or alerting rules. It gives the data a
portable shape so those backends can consume it.

For LLM applications:

```text
OpenTelemetry
  -> distributed systems view
  -> HTTP, DB, queues, services, metrics, logs, propagation

Langfuse
  -> LLM product and quality view
  -> prompts, generations, sessions, scores, traces, costs, evals
```

They work well together. A common pattern is to send rich LLM traces to
Langfuse and send operational traces, metrics, and logs to general observability
backends.

## 🔗 Signal Correlation

The signals answer different questions:

| Signal | Best question |
| --- | --- |
| Metrics | "Is something wrong in aggregate?" |
| Traces | "What happened to this request?" |
| Logs | "What did the code report at this moment?" |
| Baggage | "What request context should travel downstream?" |

A good production workflow usually starts with metrics:

```text
alert: LLM p95 latency is high
  -> metric labels show provider=openai, model=gpt-4o-mini, route=/chat
  -> trace query filters same provider/model/route
  -> one slow trace shows retry and retrieval delay
  -> logs inside that trace show provider timeout and fallback
  -> Langfuse shows prompt version and token growth for affected sessions
```

This is why correlation matters. Without shared resource attributes, trace IDs,
semantic names, and low-cardinality dimensions, every backend becomes a separate
island.

## 🌐 Environment Variables Worth Knowing

Many SDKs and instrumentations support standard environment variables. Exact
support varies by language, but these are common:

| Variable | Purpose |
| --- | --- |
| `OTEL_SERVICE_NAME` | Sets `service.name`. |
| `OTEL_RESOURCE_ATTRIBUTES` | Adds resource attributes, for example `deployment.environment.name=prod`. |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | Base OTLP endpoint, for example `http://otel-collector:4318`. |
| `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` | Signal-specific traces endpoint. |
| `OTEL_EXPORTER_OTLP_METRICS_ENDPOINT` | Signal-specific metrics endpoint. |
| `OTEL_EXPORTER_OTLP_LOGS_ENDPOINT` | Signal-specific logs endpoint. |
| `OTEL_TRACES_EXPORTER` | Selects trace exporter in supported auto-config setups. |
| `OTEL_METRICS_EXPORTER` | Selects metrics exporter in supported auto-config setups. |
| `OTEL_LOGS_EXPORTER` | Selects logs exporter in supported auto-config setups. |
| `OTEL_PROPAGATORS` | Propagators to use, commonly `tracecontext,baggage`. |
| `OTEL_TRACES_SAMPLER` | Trace sampler selection. |
| `OTEL_TRACES_SAMPLER_ARG` | Sampler argument, such as probability. |

Prefer environment configuration for deployment-specific values. Prefer code
for application-specific manual spans and metric instruments.

## 📐 Common Design Rules

### Where To Put Data

| Data | Put it in |
| --- | --- |
| Service name/version/environment | Resource attributes. |
| Operation name and duration | Span. |
| Request route/status/method | Span attributes and metric attributes. |
| User/session/tenant context needed downstream | Baggage, if safe and small. |
| Business category for filtering | Span or metric attribute, if low-cardinality. |
| Exact user input or prompt | Usually not general OTel attributes; use explicit, protected LLM observability storage if allowed. |
| Error stack trace | Correlated exception log event; put only `error.type` and status on the span. |
| Alertable totals and rates | Metrics. |
| Example request investigation | Traces. |

### Cardinality

Cardinality means "how many distinct values exist." High-cardinality attributes
can overwhelm metric backends and make traces hard to query.

Low-cardinality:

```text
route: /chat
method: POST
status_code: 500
model: gpt-4o-mini
tenant_tier: enterprise
outcome: error
```

High-cardinality:

```text
url: /chat/session/5ee3a8...?token=...
email: person@example.com
prompt: long user prompt
trace_id: unique every request
exception_message: unique message with IDs
```

For traces, high-cardinality attributes are sometimes acceptable if the backend
can handle them and the data is safe. For metrics, be much stricter.

### Span Granularity

Create spans around operations that help explain latency, errors, or behavior.

Good manual spans:

- `rag.retrieve`;
- `vector_db.query`;
- `prompt.build`;
- `llm.chat`;
- `agent.plan`;
- `agent.execute_tool`;
- `guardrail.evaluate`;
- `cache.lookup`;
- `payment.authorize`.

Avoid spans for every tiny function if they do not help investigation. Too many
spans make traces noisy and increase cost.

### Privacy

Telemetry leaves the request path and often leaves the service boundary. Treat
it as production data.

Avoid sending these to general observability backends:

- raw prompts and completions;
- retrieved document text;
- API keys and authorization headers;
- cookies;
- emails and names;
- full request/response bodies;
- full URLs with query strings;
- payment or health data;
- access tokens;
- unreviewed baggage from external callers.

If you need rich LLM payload observability, make an explicit decision about
where that data goes, how it is masked, who can access it, and how long it is
retained.

## ⚠️ Common Misunderstandings

### "The exporter is the backend"

The exporter is only the sender. It sends telemetry to a destination. The
destination might be a Collector or a backend.

```text
SDK exporter -> Collector receiver -> Collector exporter -> backend
```

There can be two exporters in the path: one in the application SDK and one in
the Collector.

### "The Collector creates my spans"

Usually no. Your application instrumentation creates spans. The Collector
receives already-created telemetry, then processes and routes it. Some Collector
receivers can create telemetry from files, host metrics, or scraped endpoints,
but distributed application traces normally start in the service.

### "Baggage automatically appears in traces"

No. Baggage is separate context. It must be explicitly copied into span
attributes, metric attributes, or logs if you want to see it in a backend.

### "Metrics can be derived from traces"

Sometimes, but do not rely on this for alerting or aggregate behavior. Traces
may be sampled. Emit metrics independently, and remember that the telemetry
delivery path still does not make them a transactional accounting record.

### "OpenTelemetry gives me observability by itself"

OTel gives you instrumentation and pipeline standards. You still need useful
spans, low-cardinality metrics, structured logs, dashboards, alerts, runbooks,
and backends.

### "Auto-instrumentation is enough"

Auto-instrumentation is a strong baseline. It usually cannot know your business
operations, product concepts, LLM prompt flow, retrieval strategy, quality
signals, or domain-specific outcomes. Add manual instrumentation where the
business meaning lives.

## 🗺️ A Minimal Production Shape

For a production service, aim for this baseline:

```text
service process
  configure SDK at startup
  set resource attributes
  enable framework/client instrumentation
  add manual business spans
  emit custom metrics
  correlate logs with traces
  export OTLP to Collector

Collector
  receive OTLP
  memory limit
  redact sensitive attributes
  add shared resource attributes
  batch
  sample traces if needed
  export traces, metrics, logs to their backends

Backends
  metrics dashboards and alerts
  trace investigation
  log search
  LLM-specific analysis in Langfuse when needed
```

## ✅ Troubleshooting Checklist

No telemetry appears:

- Is the SDK configured before app/framework clients are initialized?
- Is `service.name` set?
- Is the exporter endpoint correct?
- Is the Collector reachable from the service?
- Is the Collector receiver enabled in `service.pipelines`?
- Are spans being sampled out?
- Does the process flush on shutdown for scripts, jobs, workers, or serverless?

Traces are broken across services:

- Are both inbound and outbound instrumentations enabled?
- Are `traceparent` headers or queue metadata preserved?
- Do all services use compatible propagators, usually `tracecontext,baggage`?
- Is a proxy, API gateway, or message broker dropping metadata?
- Is context lost across threads, async tasks, or background workers?

Metrics are expensive or missing:

- Are metric attributes too high-cardinality?
- Is the metric reader configured?
- Is the metrics exporter endpoint correct?
- Does the Collector have a metrics pipeline?
- Did the backend rename metric names or labels?

Logs do not link to traces:

- Is logging instrumentation or trace-log correlation enabled?
- Are logs emitted while a span is active?
- Does the log formatter include trace and span IDs?
- Does the log backend parse those fields?

LLM traces are not useful:

- Are model calls represented as spans?
- Are provider, operation, model, route, outcome, and token usage recorded?
- Are prompts and outputs intentionally captured, masked, and routed?
- Are retrieval, reranking, tool execution, and guardrails separate spans?
- Are metrics emitted separately for latency, errors, tokens, and quality events?

## 🧭 How To Read The Rest Of These Notes

This page is the conceptual map. The rest of the OpenTelemetry notes deepen
specific parts of the map:

- [02_python_instrumentation.md](02_python_instrumentation.md) shows how to wire
  Python providers, exporters, auto-instrumentation, manual spans, metrics, and
  log correlation.
- [03_production_architecture.md](03_production_architecture.md) focuses on
  Collector topologies, production pipelines, sampling, security, and
  operations.
- [04_multi_service_examples.md](04_multi_service_examples.md) shows context
  propagation, baggage, logs, metrics, and traces across services.
- [05_custom_metrics_alerting.md](05_custom_metrics_alerting.md) explains
  metric design, Prometheus-style alerts, and runbooks.
- [06_genai_and_llm_observability.md](06_genai_and_llm_observability.md) covers
  GenAI semantic conventions and how they apply to LLM and agent systems.

## Recap

- A trace follows one execution through span IDs, shared trace identity and parent context.
- A parent reports its own outcome; a handled child failure need not fail it.
- Metrics aggregate measurements by attributes and remain independent of trace sampling.
- Baggage transports context; copying it into attributes is a separate deliberate action.
- SDK recording, Collector acceptance and backend storage are distinct delivery boundaries.

## Check yourself

**The worker starts a new trace linked to the producer. Does its database child use the producer trace ID?**

<details><summary>Answer</summary>

No. A child inherits the worker's current context. The link references the producer but does not replace parentage, so the database span remains in the worker trace.

</details>

**An error child is handled and the root returns HTTP 202. Must the root be ERROR?**

<details><summary>Answer</summary>

No. The root successfully accepted asynchronous work. Its status describes that operation, while the child retains the provider failure evidence.

</details>

**A trace is dropped by tail sampling. Must its metric and correlated log disappear?**

<details><summary>Answer</summary>

No. Independent signal pipelines export measurements and logs without inheriting that tail decision. A log's trace ID can point to a trace that is no longer retained.

</details>
