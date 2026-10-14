# Multi-Service Examples

Last verified against the OpenTelemetry Python propagation and SDK documentation on 2026-07-24.

Before reading this, understand how the SDK and instrumentation libraries are
initialized in [Python Instrumentation](02_python_instrumentation.md).

Distributed tracing only becomes useful when spans from different processes are
connected. This chapter shows how that connection works in practice for Python
services, HTTP calls, queues, baggage, logs, and metrics.

The most important distinction is that three related mechanisms solve three
different problems:

| Mechanism | Problem it solves | What normally handles it |
| --- | --- | --- |
| Local parent context | Makes a new span the child of the active span in the same process. | The OpenTelemetry Context API and SDK. |
| Remote propagation | Carries trace context and baggage across a service boundary. | Instrumented server/client libraries plus the configured propagators. |
| Baggage enrichment | Copies selected baggage values into exported span attributes. | Application code or a custom span processor. |

Auto-instrumentation can handle the first two for supported libraries. It does
not invent application baggage and it does not turn baggage into span
attributes.

## Run the same request through three processes

Prerequisites: [01 concepts](01_concepts.md) and [02 Python baseline](02_python_instrumentation.md). A process is one running application with its own provider/resource; an HTTP request crosses a process boundary, so current Python context cannot cross it directly. The client serializes context into headers and the receiver reconstructs it before starting its SERVER span.

Use [the complete local lab](../examples/README.md#run-the-local-baselines), whose files live in `examples/local`. Its deterministic agent and retriever use real FastAPI/HTTPX instrumentation and the OTel SDK. Langfuse helpers are an API convenience over that SDK; console export is the controlled destination, with no external credentials.

From the repository root after installing that lab's dependencies:

```bash
python examples/local/verify_local.py
LAB_DISABLE_TIER=1 python examples/local/verify_local.py
```

The runner starts `gateway_service.py`, `retrieval_service.py`, `agent_service.py` and the separate RAG fixture on loopback ports 8080–8083; waits for readiness; emits a request; flushes; checks exports; and stops every process it started. Those ports must be free. Its first run proves shared trace identity, allowed tier enrichment and fail-closed authentication. The changed run removes only the retrieval span processor, then proves the trace remains connected while the retrieval business span lacks the tier attribute.

To inspect the same interaction manually, start the named services using [the gateway/agent commands](../examples/02_multi_service_agent.md#run-the-complete-local-services) and add retrieval at port 8082 with `RETRIEVAL_SERVICE_URL=http://127.0.0.1:8082` on the gateway. Use a fresh request after changing any process.

Watch the two independent pieces of state:

```mermaid
sequenceDiagram
    participant U as user-a
    participant G as gateway-service
    participant R as retrieval-service
    participant A as agent-service
    U->>G: POST /chat, verified local-user-token
    Note over G: SERVER exists before handler authenticates
    G->>G: discard external baggage, set trusted enterprise
    G->>R: POST /search, CLIENT traceparent + enterprise baggage
    Note over R: extract before SERVER, on_start copies tier
    R->>R: vector_db.query inherits SERVER context
    R-->>G: document_ids=doc_001
    G->>A: POST /run, same trace ID, authenticated gateway
    A->>A: llm.decide then tool.lookup_account then llm.decide
    A-->>G: answer, steps=2
    G-->>U: answer plus trace_id
```

The gateway SERVER already exists when identity becomes trustworthy. Writing enterprise to that existing span covers this first span; attaching trusted baggage covers later children and outbound injection. Retrieval sees the carrier before it starts its SERVER, so its `TierProcessor.on_start` can copy the tier immediately. This processor affects exported attributes; traceparent extraction independently controls parentage. The runner deliberately sends attacker-supplied baggage and verifies the server-selected enterprise tier wins. Neither baggage nor trace IDs authorize account access: the internal token fixture is bound to account-a, and caller payload cannot select account-b.

The deterministic tool loop isolates propagation from paid/nondeterministic inference. [The agent continuation](../examples/02_multi_service_agent.md) explains decision steps, idempotent in-flight ownership and replacing the fake model. Retain the parent/link delayed-work policy below as a separate lifecycle choice; this synchronous HTTP lab does not claim durable queue recovery.

## 🧭 Three Separate Mechanisms

### Parent spans inside one process

No HTTP headers are involved between local spans. The active span lives in the
current execution `Context`:

```text
FastAPI SERVER span
  └── gateway.chat INTERNAL span
        └── HTTPX CLIENT span
```

When application code calls `start_as_current_span()`, the SDK makes the new
span a child of the active span:

```python
with tracer.start_as_current_span("gateway.chat"):
    await execute_chat()
```

Creating the business span is manual. Choosing its parent is automatic as long
as the correct context is current.

### Trace context between services

For HTTP, the carrier is request headers. For queues, it is message metadata.
For gRPC, it is metadata. An instrumented client injects the active context and
an instrumented server extracts it:

```text
service A active span
  -> client instrumentation creates CLIENT span
  -> propagator injects traceparent, tracestate, and baggage
  -> service B server instrumentation extracts them
  -> service B creates SERVER span with the remote parent
```

The default Python propagator configuration is equivalent to
`tracecontext,baggage`. Set it explicitly in every deployment so services do
not drift during migrations:

```bash
export OTEL_PROPAGATORS=tracecontext,baggage
```

### Baggage versus span attributes

**Baggage** is a request-scoped key-value store that can travel downstream.
**Span attributes** are values recorded on one span and exported to a backend.
Propagation keeps baggage available but does not automatically record it:

```text
baggage in Context
  -> available to downstream application code
  -> not searchable in a trace backend yet

baggage in Context
  -> allowlisted span processor
  -> attribute on each newly started span
  -> searchable in a trace backend
```

> 💡 **Key insight:** Auto-instrumentation connects spans and transports existing baggage; application code creates trusted baggage, and a processor makes selected values visible as span attributes.

---

## 🗺️ Target Architecture

Example application:

```text
client
  |
  v
gateway service
  |-- receives POST /chat
  |-- auto-starts gateway server span
  |-- attaches safe baggage
  |-- calls retrieval service
  |-- calls agent service
       |
       v
retrieval service
agent service
  |-- auto-extract trace context and baggage
  |-- auto-create child server spans
  |-- add manual business spans
  |-- copy allowlisted baggage through a registered processor
  |-- emit correlated logs and metrics
```

The desired trace:

```text
POST /chat                         gateway SERVER span
  gateway.chat                     gateway INTERNAL span
    POST retrieval /search         gateway CLIENT span
      POST /search                 retrieval SERVER span
        retrieval.search           retrieval INTERNAL span
        vector_db.query            retrieval CLIENT span
    POST agent /run                gateway CLIENT span
      POST /run                    agent SERVER span
        agent.invoke               agent INTERNAL span
          agent.plan               agent INTERNAL span
          chat gpt-4o-mini         model CLIENT span
          execute_tool search_docs tool INTERNAL span
```

The point is not the exact span names. The point is one `trace_id`, clear
service boundaries, and enough business spans to explain the request.

---

## 📐 What Is Automatic and What Is Manual

Assume FastAPI server instrumentation and HTTPX client instrumentation are
active:

| Operation | Automatic? | Application responsibility |
| --- | --- | --- |
| Start a root `SERVER` span when no valid parent arrives | Yes | None. Do not create another server span. |
| Extract inbound `traceparent`, `tracestate`, and baggage | Yes | Keep the propagator configuration compatible across services. |
| Make a manual business span a child of the active span | Yes | Create only business spans that explain latency, failure, or decisions. |
| Create an outbound HTTP `CLIENT` span | Yes | Use the instrumented HTTP client normally. |
| Inject trace context and current baggage into the outbound HTTP request | Yes | Do not also call `inject()` for the same request. |
| Decide the application baggage values | No | Authenticate, authorize, validate, and set them at the first trusted boundary. |
| Add late-created baggage to the first `SERVER` span | No | Set the attributes directly because that span already exists. |
| Copy baggage onto every subsequently created span | No built-in step | Register the allowlisted processor once in each service process. |
| Propagate through an unsupported/custom transport | No | Call `inject()` and `extract()` around that boundary. |

Here, "automatic" means the matching instrumentation is installed and enabled
on the side that owns the operation:

| Boundary | Required instrumentation |
| --- | --- |
| FastAPI inbound request | `opentelemetry-instrumentation-fastapi` in the receiving service |
| HTTPX outbound request | `opentelemetry-instrumentation-httpx` in the calling service |
| End-to-end HTTP parentage | Both of the above, plus compatible propagators in both services |

Choose one instrumentation startup model. Either run with
`opentelemetry-instrument`, or create the SDK providers and enable
instrumentation libraries in code. Doing both can register duplicate
instrumentation or exporters.

---

## 🛠️ Define and Register the Shared Baggage Processor

Put the processor implementation in a shared internal telemetry package, for
example `company_telemetry/baggage_span_processor.py`. Share the implementation,
but create and register one processor instance in every service process that
needs the attributes. The processor runs in the application SDK, not in the
Collector.

```python
# company_telemetry/baggage_span_processor.py
from __future__ import annotations

from collections.abc import Mapping

from opentelemetry import baggage, context
from opentelemetry.sdk.trace import SpanProcessor


BAGGAGE_TO_SPAN_ATTRIBUTE = {
    "session.id": "session.id",
    "app.trace.dimension.tenant_tier": "app.trace.dimension.tenant_tier",
    "app.trace.dimension.feature": "app.trace.dimension.feature",
    "app.trace.dimension.experiment": "app.trace.dimension.experiment",
    "app.request.class": "app.request.class",
}


class AllowlistedBaggageSpanProcessor(SpanProcessor):
    """Copy selected baggage values into span attributes at span start."""

    def __init__(
        self,
        attribute_map: Mapping[str, str] = BAGGAGE_TO_SPAN_ATTRIBUTE,
    ) -> None:
        self._attribute_map = dict(attribute_map)

    def on_start(self, span, parent_context=None) -> None:
        ctx = parent_context if parent_context is not None else context.get_current()
        for baggage_key, attribute_name in self._attribute_map.items():
            value = baggage.get_baggage(baggage_key, context=ctx)
            if value is not None:
                span.set_attribute(attribute_name, value)

    def on_end(self, span) -> None:
        return None

    def shutdown(self) -> None:
        return None

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return True
```

Register it exactly once, after the SDK `TracerProvider` exists and before the
process accepts requests or starts background work. In programmatic SDK setup,
registration belongs in the same telemetry bootstrap that creates the provider:

```python
# company_telemetry/bootstrap.py
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from company_telemetry.baggage_span_processor import (
    AllowlistedBaggageSpanProcessor,
)


resource = Resource.create({"service.name": "gateway"})
provider = TracerProvider(resource=resource)
provider.add_span_processor(AllowlistedBaggageSpanProcessor())
provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
trace.set_tracer_provider(provider)
```

When `opentelemetry-instrument` configures the provider, do not create a second
one. Register the custom processor on the existing SDK provider from an
application startup module that is imported before the first request:

```python
# company_telemetry/agent_bootstrap.py
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider

from company_telemetry.baggage_span_processor import (
    AllowlistedBaggageSpanProcessor,
)


provider = trace.get_tracer_provider()
if not isinstance(provider, TracerProvider):
    raise RuntimeError("OpenTelemetry SDK must be configured before app startup")

provider.add_span_processor(AllowlistedBaggageSpanProcessor())
```

The registration order relative to `BatchSpanProcessor` does not change this
processor's result because enrichment happens synchronously in `on_start()`.
Registering it first makes the startup sequence easier to audit. It cannot
retroactively enrich a span that has already started.

| Service setup | Result |
| --- | --- |
| Processor in the first gateway | Enriches business and client spans created after the gateway attaches baggage; the existing gateway `SERVER` span still needs direct attributes. |
| Processor in a downstream service | Enriches its `SERVER` span and later local spans because baggage was extracted before the server span started. |
| No processor in a service | Trace parenting and baggage propagation can still work, but baggage does not become searchable attributes on that service's spans. |

With a pre-fork server such as Gunicorn or uWSGI, initialize the SDK and
register the processor in each worker after the fork. Do not create exporter
worker threads in the parent process and then reuse them in child processes.

Do not copy every baggage key. The fixed mapping is both a security boundary and
a schema contract. Baggage has no built-in integrity guarantee and automatic
instrumentation may forward it to unintended downstream services.

---

## 🛠️ First Service: Create Trusted Baggage

The first service does not manually create `trace_id`, `span_id`, or
`traceparent`:

```text
external request without traceparent
  -> FastAPI instrumentation creates a root SERVER span
  -> application authenticates the request and creates trusted baggage
  -> HTTPX instrumentation creates a CLIENT span and injects headers
```

Its special responsibility is deciding which business values are trusted
enough to propagate. At an internet-facing boundary, drop the inbound `baggage`
header at the proxy or in a propagator filter before server instrumentation can
extract it. Caller-supplied baggage can otherwise spoof even an allowlisted key.

### Recommended solution: one dual-write helper

No span processor can retroactively enrich a span. Treat the first service's
already-running `SERVER` span as the one exception and hide the required
dual-write behind a shared helper:

```text
use_trusted_gateway_baggage()
  |-- set_attribute() on the current SERVER span
  `-- attach the same values as baggage
        `-- shared processor enriches every span created afterward
```

This keeps telemetry mechanics out of individual handlers. The handler makes
one call after authentication; the helper clears any remaining inbound baggage,
adds validated values to the existing `SERVER` span, and attaches a new context
for all later work:

```python
from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager

import httpx
from fastapi import FastAPI, Request
from opentelemetry import baggage, context, trace

from company_telemetry.baggage_span_processor import (
    BAGGAGE_TO_SPAN_ATTRIBUTE,
)

app = FastAPI()
tracer = trace.get_tracer(__name__)


@contextmanager
def use_trusted_gateway_baggage(
    values: Mapping[str, str],
) -> Iterator[None]:
    unknown_keys = set(values) - set(BAGGAGE_TO_SPAN_ATTRIBUTE)
    if unknown_keys:
        raise ValueError(f"non-allowlisted baggage keys: {sorted(unknown_keys)}")

    # Preserve the active SERVER span and trace context, but discard inbound baggage.
    ctx = baggage.clear(context.get_current())
    server_span = trace.get_current_span()

    for key, value in values.items():
        ctx = baggage.set_baggage(key, value, context=ctx)
        if server_span.is_recording():
            server_span.set_attribute(BAGGAGE_TO_SPAN_ATTRIBUTE[key], value)

    token = context.attach(ctx)
    try:
        yield
    finally:
        context.detach(token)


@app.post("/chat")
async def chat(request: Request) -> dict:
    body = await request.json()
    identity = authenticate_request(request)

    # These functions must verify ownership and return bounded values.
    values = {
        "session.id": load_authorized_session(identity, body["session_id"]),
        "app.trace.dimension.tenant_tier": validate_enum(
            identity.tenant_tier,
            {"free", "pro", "enterprise"},
        ),
        "app.trace.dimension.feature": "support_chat",
        "app.trace.dimension.experiment": validate_enum(
            experiment_service.variant_for(identity.user_id, "chat-prompt"),
            {"control", "prompt-v2"},
        ),
        "app.request.class": "interactive",
    }

    with use_trusted_gateway_baggage(values):
        with tracer.start_as_current_span("gateway.chat") as span:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.post(
                    "http://retrieval:8080/search",
                    json={"query": body["message"], "top_k": 5},
                )
                response.raise_for_status()

            documents = response.json()["documents"]
            span.set_attribute("rag.retrieved_documents", len(documents))
            return {"documents": documents}
```

There is no `inject()` call. HTTPX instrumentation creates the outbound
`CLIENT` span and injects the active trace context and baggage.

> ⚠️ **Watch out:** The gateway `SERVER` span starts before handler-created baggage exists, so the processor cannot enrich it retroactively; set those attributes directly on the current span, then let the processor handle spans created afterward.

The two writes have different destinations and are both required:

| Operation | Affects |
| --- | --- |
| `server_span.set_attribute(...)` | Only the `SERVER` span that already exists. |
| `baggage.set_baggage(...)` plus `context.attach(...)` | Business/client spans created later and downstream services. |

### Alternative: create baggage before the server span

If the processor must enrich even the first `SERVER` span, the trusted claims
must exist before OpenTelemetry starts that span:

```text
external request
  -> outer authentication middleware or trusted ingress
       |-- validate credentials
       |-- discard caller-supplied baggage
       `-- attach trusted claims as baggage
  -> OpenTelemetry server instrumentation starts SERVER span
  -> baggage processor sees the claims during on_start()
```

This requires authentication to wrap the OpenTelemetry middleware, or a trusted
upstream gateway that authenticates the request before it reaches the service.
Middleware ordering and header sanitization become part of the security
boundary. A FastAPI dependency, handler, or ordinary inner authentication
middleware still runs too late.

Use this alternative only when authentication already lives at that outer
boundary. Otherwise, the dual-write helper is simpler and makes the timing
explicit.

Good baggage values are bounded categories or opaque IDs such as tenant tier,
experiment variant, authorized session ID, request class, or region. Never use
access tokens, API keys, email addresses, raw prompts, retrieved documents, or
request bodies.

---

## 🛠️ Downstream Service: Use the Extracted Context

In a downstream service, FastAPI instrumentation extracts baggage before it
starts the `SERVER` span. The registered processor can therefore copy baggage
onto both that span and later child spans. Handler code adds only business
instrumentation:

```python
@app.post("/search")
async def search(request: Request) -> dict:
    body = await request.json()

    with tracer.start_as_current_span("retrieval.search") as span:
        span.set_attribute("rag.top_k", body["top_k"])
        documents = vector_store.search(body["query"], top_k=body["top_k"])
        span.set_attribute("rag.retrieved_documents", len(documents))
        return {"documents": documents}
```

Do not call `extract()` and do not create another server span. A manual
`retrieval.search` span is useful because it describes the business operation;
its parent is chosen from the current FastAPI server context.

The complete automatic path is:

```text
incoming request
  -> FastAPI instrumentation extracts traceparent and baggage
  -> FastAPI creates SERVER span
  -> baggage processor copies allowlisted values onto that new span
  -> your handler runs with that span active
  -> HTTPX instrumentation creates CLIENT span
  -> baggage processor copies allowlisted values onto that new span
  -> HTTPX injects traceparent and baggage into outbound headers
```

---

## 🔗 When Manual Propagation Is Correct

Use manual propagation only when no instrumentation owns the transport, when
building instrumentation itself, or in a focused propagation test:

```python
from opentelemetry.propagate import extract, inject


outgoing_carrier: dict[str, str] = {}
inject(outgoing_carrier)

# `send()` performs the transport; `inject()` only populated the carrier.
custom_transport.send(payload, metadata=outgoing_carrier)

incoming_carrier = received_metadata
parent_ctx = extract(incoming_carrier)
with tracer.start_as_current_span(
    "custom_transport.process",
    context=parent_ctx,
):
    process(payload)
```

Do not combine this pattern with working HTTPX/FastAPI propagation for the same
request. Queues and other asynchronous boundaries need additional parent-versus-
link decisions covered later in this chapter.

---

## 📦 What Headers Look Like

For HTTP, W3C Trace Context uses `traceparent`:

```text
traceparent: 00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01
```

Parts:

```text
version: 00
trace_id: 4bf92f3577b34da6a3ce929d0e0e4736
span_id: 00f067aa0ba902b7
trace_flags: 01
```

`tracestate` carries vendor-specific trace state:

```text
tracestate: vendor1=value1,vendor2=value2
```

`baggage` carries request context:

```text
baggage: app.trace.dimension.tenant_tier=enterprise,app.trace.dimension.experiment=reranker_b
```

Do not log full inbound headers unless you redact first. Headers may contain
credentials and baggage.

> ⚠️ **Watch out:** Logging raw inbound headers leaks authorization tokens, cookies, and the full baggage string — always redact before logging headers in any context.

## 🔗 Correlate Traces, Logs, And Metrics

Inside any service, traces, metrics, and logs should share enough context to
move between them during incidents.

```python
import logging
from opentelemetry import metrics, trace

logger = logging.getLogger(__name__)
meter = metrics.get_meter(__name__)
tracer = trace.get_tracer(__name__)

retrieval_results = meter.create_histogram(
    "rag.retrieved_documents",
    unit="{document}",
    description="Documents returned by retrieval.",
)


def rerank(query: str, documents: list[dict]) -> list[dict]:
    with tracer.start_as_current_span("retrieval.rerank") as span:
        ranked = reranker.rank(query, documents)

        attrs = {"rag.retrieval.strategy": "hybrid_rerank"}
        span.set_attribute("rag.candidate_documents", len(documents))
        span.set_attribute("rag.returned_documents", len(ranked))
        retrieval_results.record(len(ranked), attrs)

        logger.info(
            "reranked documents",
            extra={
                "candidate_documents": len(documents),
                "returned_documents": len(ranked),
            },
        )
        return ranked
```

This gives:

- trace detail for one request;
- metric trends for all requests;
- logs with the active trace and span IDs.

Metric attributes should remain low-cardinality. Do not add trace IDs, user IDs,
prompts, or full queries to metric attributes.

## 🔄 Propagation Through Queues

Queue propagation uses a carrier stored in message headers or metadata. The
carrier is only the serialized propagation data; `queue.publish()` performs the
actual transport:

```python
from opentelemetry.propagate import extract, inject


def publish_job(queue, payload: dict) -> None:
    with tracer.start_as_current_span(
        "orders publish",
        kind=trace.SpanKind.PRODUCER,
        attributes={
            "messaging.system": "rabbitmq",
            "messaging.destination.name": "orders",
            "messaging.operation.type": "publish",
        },
    ) as producer:
        carrier: dict[str, str] = {}
        # Inject from the active PRODUCER span, not its parent request span.
        inject(carrier)
        queue.publish(payload, headers=carrier)


def consume_job(message) -> None:
    carrier = message.headers
    parent_ctx = extract(carrier)
    with tracer.start_as_current_span(
        "orders process",
        context=parent_ctx,
        kind=trace.SpanKind.CONSUMER,
        attributes={
            "messaging.system": "rabbitmq",
            "messaging.destination.name": "orders",
            "messaging.operation.type": "process",
        },
    ):
        process(message.payload)
```

This creates a parent-child relationship:

```text
POST /chat
  orders publish             PRODUCER
    orders process           CONSUMER
```

Use this when the worker job is causally part of the same request.

Call `inject(carrier)` inside the `PRODUCER` span, not before it, so the
consumer sees the producer as its parent. Injecting from an outer span skips the
queue boundary and produces a misleading trace shape. `inject()` only mutates
`carrier`; `queue.publish(..., headers=carrier)` is the operation that sends it.

## 🔗 Span Links For Decoupled Work

Sometimes a queued job is related but not a direct child:

- the job may run much later;
- one batch consumes many messages;
- one message triggers many independent jobs;
- several upstream events contribute to one downstream operation.

Use span links.

```python
from opentelemetry import context as otel_context, trace
from opentelemetry.propagate import extract
from opentelemetry.trace import Link


def process_batch(messages: list) -> None:
    links: list[Link] = []

    for message in messages:
        carrier = message.headers
        message_ctx = extract(carrier)
        span_context = trace.get_current_span(message_ctx).get_span_context()
        if span_context.is_valid:
            links.append(Link(span_context))

    with tracer.start_as_current_span(
        "worker.process_batch",
        # `None` would reuse the current context. An explicit empty context
        # guarantees that this linked operation starts a new trace.
        context=otel_context.Context(),
        kind=trace.SpanKind.CONSUMER,
        links=links,
    ) as span:
        span.set_attribute("messaging.batch.message_count", len(messages))
        process_messages(messages)
```

Links say "related to these contexts" without pretending there is one parent.
The empty `Context()` is what makes `worker.process_batch` a root span. In the
Python API, omitting `context` or passing `None` uses the current context; if a
queue instrumentation has already activated a consumer span, the batch span
would otherwise become its child and remain in that trace.

Verify the exported shape rather than only checking that `links` is populated:

```text
worker.process_batch
  trace_id != every producer trace_id
  parent_span_id = empty
  links = one producer SpanContext per message with valid propagated context
```

⚠️ `Context()` only controls the parent of the manual span. It cannot remove an
automatic `CONSUMER` span that was created before `process_batch()` ran. If the
instrumentation already emits the root-plus-links topology you want, use that
span instead of creating a duplicate. If it emits different semantics, disable
that queue instrumentation in the worker process and let the handler own
extraction, root creation, links, and the consumer span. Keep unrelated HTTP,
database, and client instrumentations enabled. The Python-specific ownership
and selective-disable choices are covered in
[Python Instrumentation](02_python_instrumentation.md).

## 🗄️ Durable Database Handoffs

A database-backed queue, outbox, lease, or persisted workflow transition is a
transport boundary even though SQL instrumentation already emits database
spans. The `SELECT`, claim, or polling span describes storage activity; it is
not the causal parent of work that was scheduled earlier.

Persist a W3C carrier with the work item or runnable state:

```text
work row
  payload / state
  trace carrier = {
    "traceparent": "00-...",
    "tracestate": "..."   # optional
  }
  workflow_run_id = "..." # business correlation, not propagation
```

Store `traceparent` plus optional `tracestate`, not a bare trace ID or a
serialized SDK context. Inject the carrier while the scheduling/transition span
is current and commit it atomically with the work or state change. If the
transaction rolls back, neither the runnable work nor its carrier may become
visible.

Durable, delayed, or independently retried work normally starts a new root with
a link to the scheduling context:

```python
from opentelemetry import context as otel_context, propagate, trace
from opentelemetry.trace import Link


def run_claimed_transition(row) -> None:
    incoming = propagate.extract(
        row.otel_context or {},
        context=otel_context.Context(),
    )
    scheduling_context = trace.get_current_span(incoming).get_span_context()
    links = [Link(scheduling_context)] if scheduling_context.is_valid else []

    with tracer.start_as_current_span(
        "run workflow transition",
        context=otel_context.Context(),
        links=links,
        attributes={
            "app.workflow.name": row.workflow_name,
            "app.workflow.run.id": row.workflow_run_id,
            "app.workflow.attempt": row.attempt,
        },
        record_exception=False,
    ):
        apply_transition(row)
```

Extract from an explicit empty context and create the processing span from an
explicit empty context. Otherwise a poll-loop, lease, or DB client span that
happens to be current can become the accidental parent. A valid linked trace
has a new `trace_id`, no parent span ID, and exactly one link to the scheduling
context.

Lifecycle rules:

- Preserve the original scheduling carrier across retries of the same work
  item; change only a bounded attempt attribute.
- When a successful transition makes the next state runnable, inject a fresh
  carrier from that transition span and persist it with the next state.
- Treat stored carriers as untrusted input. Missing, malformed, or oversized
  values must produce an unlinked root and must never fail or authorize work.
- Put a stable workflow/run ID on transition spans and important boundary logs
  so several linked traces remain searchable. Never use it as a metric label.
- Ensure exactly one owner creates the work-processing boundary; generic DB
  instrumentation remains useful for queries but does not replace it.

## 🔄 Async Tasks And Threads

Context usually flows through normal async call paths, but it can be lost when
work moves into background tasks, thread pools, subprocesses, or custom
schedulers.

Pattern for explicit context capture:

```python
from opentelemetry import context


def submit_background_work(executor, payload: dict) -> None:
    current_ctx = context.get_current()
    executor.submit(run_with_context, current_ctx, payload)


def run_with_context(parent_ctx, payload: dict) -> None:
    token = context.attach(parent_ctx)
    try:
        with tracer.start_as_current_span("background.process"):
            process(payload)
    finally:
        context.detach(token)
```

If spans suddenly become roots when work leaves the request handler, suspect
context loss.

When spans unexpectedly start a new trace instead of becoming children, first
check whether context was lost at the async boundary. Capture it explicitly
before handing work to a thread pool, executor, or background task.

## 🔗 Propagation Through gRPC And Custom Transports

For gRPC, use gRPC instrumentation where available. It should handle metadata
injection and extraction.

For a custom transport, apply the earlier manual `inject()`/`extract()` pattern.
Choose a metadata carrier that both sender and receiver preserve.

Requirements for a custom carrier:

- it must preserve `traceparent`;
- it should preserve `tracestate`;
- it should preserve `baggage` only if baggage is safe for that boundary;
- it must not expose tracing metadata to user-visible payloads;
- it should survive serialization and broker hops.

## Follow a durable carrier through a lifecycle boundary

The database handoff below is a protocol trace, not a complete database implementation. It combines earlier carrier serialization with the new-root link policy already taught in 01:

```mermaid
sequenceDiagram
    participant S as scheduler span
    participant DB as task row and carrier
    participant P as worker poll span
    participant W as linked execution root
    S->>DB: atomic commit payload plus injected carrier
    P->>DB: claim committed task under transaction
    DB-->>P: task payload plus producer context
    P->>W: start with empty parent, link to stored producer
    W->>DB: perform work then commit completion
```

The commit makes payload and correlation visible together; a worker cannot observe a task with missing context from a separate unfinished write. Polling is worker infrastructure, so the new execution root does not inherit the poll span. Its explicit link refers to the scheduler context retained in the row. This topology says nothing about exactly-once execution: a worker crash after a side effect and before completion still needs application idempotency and ownership fencing, as developed in the agent example.

## 🌐 Propagator Configuration

All services should agree on propagators. Common setting:

```bash
export OTEL_PROPAGATORS=tracecontext,baggage
```

If one service uses W3C Trace Context and another only understands a different
format, traces will break at that boundary.

During migrations, some teams configure multiple propagators. Be explicit and
document the compatibility period.

## 🔗 Baggage And Langfuse Context

For LLM applications, you often need user, session, release, prompt, or
experiment context across spans.

General OTel baggage keys:

```text
session.id
app.trace.dimension.tenant_tier
app.trace.dimension.feature
app.trace.dimension.experiment
app.request.class
```

Langfuse-specific trace fields:

```text
langfuse.user.id
langfuse.session.id
langfuse.release
langfuse.trace.metadata.customer_tier
langfuse.observation.metadata.tool_family
```

Use `app.*` when the context is generally useful. Use `langfuse.*` when you are
intentionally mapping fields into Langfuse. Do not put raw prompts or documents
in baggage.

## End-to-end observations and their limits

Use the runner above as the canonical local composition. A shared trace ID alone proves grouping; also compare each remote SERVER parent ID to its HTTPX CLIENT span ID to establish the actual call relationship. Resources must name different services, and the tier must appear only where a processor/helper explicitly copies it. Console export proves the SDK payload, not Collector or external backend delivery. Use the deployment canary in the deployment guide for those later boundaries.

## 🔍 Troubleshooting Broken Traces

Every service starts a new trace:

- inbound extraction is missing;
- outgoing injection is missing;
- services use incompatible propagators;
- proxies strip `traceparent`;
- manual extraction happens too late.

Client span has no matching server span:

- downstream service is not instrumented;
- request went through a proxy that dropped headers;
- service exports to a different backend;
- sampling dropped one side;
- route handler starts a new root span manually.

Baggage missing:

- `OTEL_PROPAGATORS` does not include `baggage`;
- baggage was set after headers were injected;
- context was not attached;
- downstream service did not copy baggage to span attributes;
- baggage key was filtered or too large for headers.

Logs do not correlate:

- logging instrumentation is missing;
- log formatter does not include trace/span IDs;
- logs are emitted outside the active span;
- background worker lost context.

Queue jobs have an unexpected trace shape:

- expected parent-child but got an unlinked root: producer injection, consumer
  extraction, or broker metadata preservation failed;
- expected a linked root but got the producer trace: the consumer reused the
  extracted or current context as parent instead of passing an empty context;
- expected one consumer span but got two: auto-instrumentation and manual code
  both own the consumer boundary;
- expected links but got none: the carrier did not contain a valid propagated
  `SpanContext`, or the getter read the wrong message-attribute representation.

## ✅ Design Checklist

- Use auto-instrumentation for standard HTTP/gRPC/database/queue clients only
  after its emitted parent/link semantics match the intended trace policy.
- Add manual spans around business operations.
- Use manual `inject()` and `extract()` where auto-instrumentation does not
  apply or where the queue boundary deliberately needs custom parent/link
  semantics.
- Create trusted application baggage at the first trusted service boundary.
- Set baggage-derived attributes directly on that service's already-running
  `SERVER` span.
- Register the allowlisted baggage processor exactly once in every service
  process that should expose those values as span attributes.
- Keep baggage small, safe, and allowlisted.
- Drop untrusted inbound baggage and confirm third-party calls do not receive
  internal baggage.
- Use span links for decoupled or batch work.
- Persist durable-work W3C carriers atomically with the work/state transition.
- Start delayed or independently retried durable work as an empty-context root
  linked to the scheduling carrier, never as a child of a poll/claim span.
- Keep workflow/run IDs on spans and important logs, never on metrics.
- Keep metrics independent from traces.
- Confirm trace IDs match across services in a local or staging trace.
- Confirm logs include trace IDs for request-scoped messages.

## 🔗 References

- [OpenTelemetry Python propagation](https://opentelemetry.io/docs/languages/python/propagation/)
- [OpenTelemetry Python tracing API](https://opentelemetry-python.readthedocs.io/en/stable/api/trace.html)
- [OpenTelemetry Python agent configuration](https://opentelemetry.io/docs/zero-code/python/configuration/)
- [OpenTelemetry Boto3 SQS instrumentation](https://opentelemetry-python-contrib.readthedocs.io/en/latest/instrumentation/boto3sqs/boto3sqs.html)
- [OpenTelemetry Boto3 SQS 0.65b0 source](https://github.com/open-telemetry/opentelemetry-python-contrib/blob/v0.65b0/instrumentation/opentelemetry-instrumentation-boto3sqs/src/opentelemetry/instrumentation/boto3sqs/__init__.py)
- [OpenTelemetry baggage](https://opentelemetry.io/docs/concepts/signals/baggage/)
- [OpenTelemetry Python propagator API](https://opentelemetry-python.readthedocs.io/en/latest/api/propagate.html)
- [OpenTelemetry Python `SpanProcessor` API](https://opentelemetry-python.readthedocs.io/en/latest/sdk/trace.html)
- [OpenTelemetry Python pre-fork server setup](https://opentelemetry-python.readthedocs.io/en/latest/examples/fork-process-model/README.html)
- [FastAPI instrumentation](https://opentelemetry-python-contrib.readthedocs.io/en/latest/instrumentation/fastapi/fastapi.html)
- [HTTPX instrumentation](https://opentelemetry-python-contrib.readthedocs.io/en/latest/instrumentation/httpx/httpx.html)

**Next**: [Custom Metrics and Alerting](05_custom_metrics_alerting.md)

## Recap

- Context travels in HTTP headers because processes cannot share Python execution context.
- Extract before starting a remote SERVER span to preserve the caller relationship.
- Authenticate before adding trusted business baggage and reject caller-controlled identity.
- Baggage enrichment and trace propagation are separate; one can work while the other fails.
- Delayed work can continue a trace or start a linked trace under an explicit lifecycle policy.

## Check yourself

**Remove retrieval's TierProcessor but keep HTTP instrumentation. What changes?**

<details><summary>Answer</summary>

Trace IDs and remote parentage stay connected because headers are still injected/extracted. The tier remains transported context but no longer becomes a retrieval span attribute. Missing attributes are not proof of broken trace propagation.

</details>

**A public caller sends enterprise baggage and account-b. Which account may the agent read?**

<details><summary>Answer</summary>

Only account-a in this lab, derived from the verified gateway identity. The public request schema carries no account selection, and the gateway clears external baggage. Telemetry context cannot grant access.

</details>

## Try it

Run the changed processor case above, then locate the retrieval business span and gateway business span in the exported output. Leave the diagnosis to yourself before opening the answer.

<details><summary>Worked solution</summary>

Retrieval lacks app.tenant.tier but still shares the gateway trace ID. Restore processor registration, restart that process, and send a fresh request. The attribute returns without changing traceparent ownership.

</details>
