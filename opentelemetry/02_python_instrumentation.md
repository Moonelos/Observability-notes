# Python Instrumentation

This chapter turns the concepts from [01_concepts.md](01_concepts.md) into a
Python service setup. The goal is not just to paste a startup snippet. The goal
is to understand where each piece belongs in a real process:

```text
Python application starts
  -> configure Resource
  -> configure TracerProvider, MeterProvider, optional LoggerProvider
  -> attach processors, metric readers, exporters
  -> install framework/client instrumentations
  -> handle requests and background work
  -> create automatic and manual spans
  -> record metrics
  -> correlate logs
  -> flush on shutdown
```

The examples use FastAPI, HTTPX, and OTLP/HTTP, but the same pattern applies to
Flask, Django, Celery, workers, CLIs, and batch jobs.

## 🧭 The Python Mental Model

In Python, there are three layers you need to keep separate:

| Layer | Package family | What it does |
| --- | --- | --- |
| API | `opentelemetry-api` | Gives instrumentation code `trace.get_tracer()`, `metrics.get_meter()`, context, baggage, and propagators. |
| SDK | `opentelemetry-sdk` | Implements providers, resources, span processors, metric readers, aggregation, sampling, and exporting. |
| Instrumentation | `opentelemetry-instrumentation-*` | Hooks frameworks and client libraries to create spans, metrics, propagation, and log correlation automatically. |

Library code should usually depend only on the API. Application startup code
owns the SDK configuration.

If no SDK provider is configured, API calls become no-ops. This lets shared
libraries add spans without deciding your backend.

## 📐 Code-Based vs Zero-Code Instrumentation

Python supports two common setup styles.

| Style | How it works | Best for |
| --- | --- | --- |
| Code-based | Your app imports a startup module and configures providers and instrumentors directly. | Production services where you want explicit control. |
| Zero-code | The `opentelemetry-instrument` launcher injects SDK and instrumentation setup using environment variables. | Fast trials, platform-managed instrumentation, or apps where code changes are hard. |

Do not mix them casually. If `opentelemetry-instrument` configures the SDK and
your app also calls `trace.set_tracer_provider()`, you can end up with double
instrumentation, no-op providers, duplicate spans, or configuration that silently
loses data. Pick one owner for provider setup.

> ⚠️ **Watch out:** Mixing zero-code and code-based setup in the same process silently produces duplicate spans or discarded telemetry — pick one approach and let it own provider initialization.

These notes mostly use code-based setup because it is easier to reason about in
application code. A zero-code section appears later in this file.

## Run one complete service before choosing exporters

Prerequisites: basic Python, a terminal, and the trace/context model in 01. Run commands from the repository root. This local lab needs no Collector, database, model provider, or credentials. It owns provider setup directly; launch it with plain Uvicorn.

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install 'fastapi>=0.115,<1' 'uvicorn>=0.30,<1' 'opentelemetry-sdk>=1.39,<2' 'opentelemetry-instrumentation-fastapi>=0.60b0,<1'
cd examples/local
uvicorn chat_app:app --host 127.0.0.1 --port 8080
```

In another terminal:

```bash
curl --fail-with-body -sS http://127.0.0.1:8080/chat -H 'content-type: application/json' -d '{"question":"How do I reset SSO?"}'
```

The response contains an approved stub answer and a 32-character trace ID. The console prints `rag.retrieve` and `POST /chat` with that same ID, different span IDs, and the retrieval span's parent equal to the server span's ID. ASGI may also emit receive/send child spans; those describe protocol work rather than additional retrievals. No question content enters the trace.

The complete file is [chat_app.py](../examples/local/chat_app.py); the source below is the same baseline, not another app to combine with later variants:

```python
"""Complete console-first FastAPI baseline. Launch from this directory."""
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI
from pydantic import BaseModel, Field
from opentelemetry import trace, metrics
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor, BatchSpanProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import ConsoleMetricExporter, PeriodicExportingMetricReader
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

resource = Resource.create({'service.name': 'chat-api', 'service.instance.id': str(uuid.uuid4()),
                            'deployment.environment.name': 'development', 'service.version': 'local-lab'})
provider = TracerProvider(resource=resource)
if os.getenv('LAB_OTLP_ENDPOINT'):
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=os.environ['LAB_OTLP_ENDPOINT'])))
else:
    provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
trace.set_tracer_provider(provider)
reader = PeriodicExportingMetricReader(ConsoleMetricExporter(), export_interval_millis=60000)
meter_provider = MeterProvider(resource=resource, metric_readers=[reader])
metrics.set_meter_provider(meter_provider)
tracer = trace.get_tracer('lab.chat')
meter = metrics.get_meter('lab.chat')
requests = meter.create_counter('app.chat.requests', unit='{request}')
duration = meter.create_histogram('app.chat.duration', unit='s')
logging.basicConfig(level=logging.INFO, format='%(message)s')

@asynccontextmanager
async def lifespan(app):
    try:
        yield
    finally:
        meter_provider.force_flush()
        provider.shutdown()
        meter_provider.shutdown()

app = FastAPI(lifespan=lifespan)
FastAPIInstrumentor.instrument_app(app, tracer_provider=provider, meter_provider=meter_provider)

class Chat(BaseModel):
    question: str = Field(min_length=1, max_length=4000)

@app.post('/chat')
def chat(body: Chat):
    started = time.perf_counter()
    with tracer.start_as_current_span('rag.retrieve', record_exception=False) as span:
        span.set_attribute('rag.documents.returned', 1)
        # Product content is returned to the caller, never attached to telemetry.
        answer = 'Workspace admins reset SSO in Security settings. [doc_001]'
    current = trace.get_current_span().get_span_context()
    attrs = {'http.route': '/chat', 'app.outcome': 'success'}
    requests.add(1, attrs)
    duration.record(time.perf_counter() - started, attrs)
    logging.info('retrieved=1 trace_id=%032x span_id=%016x', current.trace_id, current.span_id)
    return {'answer': answer, 'trace_id': f'{current.trace_id:032x}'}
```

Follow who creates the parent before examining export:

```mermaid
sequenceDiagram
    participant C as curl
    participant F as FastAPI chat-api
    participant S as OTel SDK
    participant E as Console exporter
    C->>F: POST /chat question=SSO reset
    F->>S: start SERVER POST /chat
    F->>S: start rag.retrieve in current context
    S->>E: end rag.retrieve, parent=SERVER ID
    F-->>C: answer plus trace_id
    S->>E: end POST /chat, same trace_id
```

FastAPI first establishes the server span as current. Retrieval then reads that context and becomes a child. Ending either span triggers export; exporting never chooses its parent. The SDK and the business response therefore have separate success conditions. The log prints IDs read from the same current server context. The application counter increments once per request and its histogram records elapsed seconds; shutdown collects those measurements rather than waiting a full minute. Press Ctrl-C once to stop accepting requests and flush before providers stop.

### Change the destination while preserving the tree

First run a long-lived loopback debug receiver in another terminal. Install the pinned Collector binary using [deployment decisions](deployment/01_deployment_decisions.md); save this complete config as `console-collector.yaml` in `examples/local`:

```yaml
receivers:
  otlp:
    protocols:
      http:
        endpoint: 127.0.0.1:19419
exporters:
  debug:
    verbosity: detailed
service:
  pipelines:
    traces:
      receivers: [otlp]
      exporters: [debug]
```

```bash
otelcol-contrib validate --config console-collector.yaml
otelcol-contrib --config console-collector.yaml
```

Port 19419 must be free; if startup reports an address conflict, choose a free loopback port in both the receiver and exporter. Do not send the lab request until your own receiver is running. Keep it running, install the OTLP exporter in the application environment, and restart the app with a full signal URL:

```bash
python -m pip install 'opentelemetry-exporter-otlp-proto-http>=1.39,<2'
LAB_OTLP_ENDPOINT=http://127.0.0.1:19419/v1/traces uvicorn chat_app:app --host 127.0.0.1 --port 8080
```

Only the trace exporter and processor change: the OTLP branch batches completed spans while the console branch exports synchronously for visibility. The resource, server/manual span ownership and context rule stay the same. Keep console metrics until the later metric-export section; setting this lab variable does not switch metrics. If the Collector is stopped, `/chat` still returns its answer while exporter errors appear. Restart the receiver and emit a **new** request: a successful new trace proves restoration, not replay of every lost old span.

## 🔌 Install Packages

Install only what you use. A typical FastAPI service that emits traces and
metrics over OTLP/HTTP and correlates logs needs:

```bash
pip install fastapi uvicorn httpx opentelemetry-api \
  opentelemetry-sdk \
  opentelemetry-exporter-otlp-proto-http \
  opentelemetry-instrumentation-fastapi \
  opentelemetry-instrumentation-httpx \
  opentelemetry-instrumentation-logging
```

Add instrumentation packages for the libraries in your request path:

```bash
pip install opentelemetry-instrumentation-sqlalchemy \
  opentelemetry-instrumentation-redis \
  opentelemetry-instrumentation-celery
```

Use the OTLP HTTP exporter when your Collector listens on `4318`. Use the OTLP
gRPC exporter when it listens on `4317`.

```bash
pip install opentelemetry-exporter-otlp-proto-grpc
```

The package set should match your deployment. Do not install every
instrumentation package "just in case"; each instrumentation hooks imports or
library internals and should be intentional.

## 🌐 Environment Configuration

Use environment variables for deployment-specific values:

```bash
export OTEL_SERVICE_NAME=chat-api
export OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4318
export OTEL_PROPAGATORS=tracecontext,baggage
export OTEL_TRACES_SAMPLER=parentbased_traceidratio
export OTEL_TRACES_SAMPLER_ARG=1.0
export SERVICE_VERSION=$(git rev-parse --short HEAD)
export ENVIRONMENT=production
```

Common variables:

| Variable | Meaning |
| --- | --- |
| `OTEL_SERVICE_NAME` | Sets the logical service name. Required for useful backends. |
| `OTEL_RESOURCE_ATTRIBUTES` | Adds resource attributes such as `deployment.environment.name=production`. |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | Base OTLP endpoint. For HTTP, usually `http://collector:4318`. |
| `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` | Signal-specific traces endpoint. |
| `OTEL_EXPORTER_OTLP_METRICS_ENDPOINT` | Signal-specific metrics endpoint. |
| `OTEL_EXPORTER_OTLP_LOGS_ENDPOINT` | Signal-specific logs endpoint. |
| `OTEL_EXPORTER_OTLP_HEADERS` | Static exporter headers, often credentials. |
| `OTEL_EXPORTER_OTLP_<SIGNAL>_HEADERS` | Signal-specific headers that override the common headers for that signal. |
| `OTEL_EXPORTER_OTLP_PROTOCOL` | Common OTLP transport, usually `http/protobuf` or `grpc`. |
| `OTEL_EXPORTER_OTLP_<SIGNAL>_PROTOCOL` | Signal-specific transport override. |
| `OTEL_PROPAGATORS` | Propagators, commonly `tracecontext,baggage`. |
| `OTEL_TRACES_SAMPLER` | Trace sampler name. |
| `OTEL_TRACES_SAMPLER_ARG` | Trace sampler argument, such as probability. |

Prefer `deployment.environment.name` over older ad hoc names such as `env`.
If your code uses a local `ENVIRONMENT` variable, convert it into the OTel
resource attribute during startup.

### Common Defaults And Signal-Specific Overrides

Traces, metrics, and logs do not have to use the same destination. Every common
OTLP exporter option has a signal-specific form, and the signal-specific value
takes precedence for that signal:

```text
OTEL_EXPORTER_OTLP_<SIGNAL>_<OPTION>
  -> otherwise OTEL_EXPORTER_OTLP_<OPTION>
       -> otherwise the SDK/exporter default
```

`<SIGNAL>` is `TRACES`, `METRICS`, or `LOGS`. Common options include endpoint,
headers, protocol, compression, timeout, certificates, and client keys.
Language support varies, so verify the SDK's environment-variable compliance
before depending on a less common option.

#### One OTLP/HTTP Base Endpoint

When every signal goes to the same OTLP/HTTP receiver, one base endpoint is
enough:

```bash
export OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf
export OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4318
```

The OTLP/HTTP exporter constructs the signal URLs:

```text
traces  -> http://otel-collector:4318/v1/traces
metrics -> http://otel-collector:4318/v1/metrics
logs    -> http://otel-collector:4318/v1/logs
```

If the base contains a path, the signal path is appended below it:

```bash
export OTEL_EXPORTER_OTLP_ENDPOINT=https://telemetry.example.com/ingest
```

```text
traces  -> https://telemetry.example.com/ingest/v1/traces
metrics -> https://telemetry.example.com/ingest/v1/metrics
logs    -> https://telemetry.example.com/ingest/v1/logs
```

#### Split Destinations

Set full signal-specific endpoints when signals need different receivers:

```bash
export OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=\
http://otel-collector:4318/v1/traces
export OTEL_EXPORTER_OTLP_METRICS_ENDPOINT=\
https://metrics.example.com/v1/metrics
```

The result is:

```text
traces  -> OpenTelemetry Collector
metrics -> metrics.example.com
```

A common default plus one override is also valid:

```bash
export OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4318
export OTEL_EXPORTER_OTLP_METRICS_ENDPOINT=\
https://metrics.example.com/v1/metrics
```

```text
traces  -> http://otel-collector:4318/v1/traces
logs    -> http://otel-collector:4318/v1/logs
metrics -> https://metrics.example.com/v1/metrics
```

#### The OTLP/HTTP Path Rule

The general and signal-specific endpoint variables have intentionally different
path behavior:

| Configuration | OTLP/HTTP behavior |
| --- | --- |
| `OTEL_EXPORTER_OTLP_ENDPOINT=http://collector:4318` | Treat it as a base and append `/v1/traces`, `/v1/metrics`, or `/v1/logs`. |
| `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=http://collector:4318/custom` | Send traces to `/custom` exactly; do not append `/v1/traces`. |
| `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=http://collector:4318` | Send traces to the root path `/`, which is usually not an OTLP/HTTP traces endpoint. |

This rule is a common cause of `404` responses. For a standard Collector
receiver, this signal-specific setting is normally correct:

> ⚠️ **Watch out:** Setting `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` to a bare host:port (without `/v1/traces`) sends to the root path `/` and gets a `404` — the signal-specific variable is used as-is, not treated as a base URL.

```bash
export OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=\
http://otel-collector:4318/v1/traces
```

Do not append HTTP signal paths to OTLP/gRPC endpoints. A gRPC exporter connects
to a target such as `http://otel-collector:4317` and calls the signal's protobuf
service method:

```bash
export OTEL_EXPORTER_OTLP_PROTOCOL=grpc
export OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4317
```

#### Per-Signal Protocols And Credentials

Signals can also use different protocols and authentication:

```bash
export OTEL_EXPORTER_OTLP_TRACES_PROTOCOL=grpc
export OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=\
http://trace-collector:4317
export OTEL_EXPORTER_OTLP_TRACES_HEADERS=\
x-api-key=trace-token

export OTEL_EXPORTER_OTLP_METRICS_PROTOCOL=http/protobuf
export OTEL_EXPORTER_OTLP_METRICS_ENDPOINT=\
https://metrics.example.com/v1/metrics
export OTEL_EXPORTER_OTLP_METRICS_HEADERS=\
x-api-key=metrics-token
```

Inject header values from secret management. Do not commit exporter credentials
to source control or bake them into container images.

The explicit Python imports later in this chapter use
`opentelemetry.exporter.otlp.proto.http`, so that code has already chosen
OTLP/HTTP with protobuf. Protocol environment variables are primarily useful
when a distro or zero-code launcher selects the exporter. To change the
code-based example to gRPC, install and import the gRPC exporter package rather
than expecting `OTEL_EXPORTER_OTLP_PROTOCOL` to replace the imported class.

#### Direct OTLP Metrics To Prometheus

Prometheus can receive OTLP metrics over HTTP when its OTLP receiver is enabled:

```bash
prometheus --web.enable-otlp-receiver
```

The receiver listens on `/api/v1/otlp/v1/metrics`. Because a signal-specific
endpoint is used as-is, supply that complete path:

```bash
export OTEL_TRACES_EXPORTER=otlp
export OTEL_METRICS_EXPORTER=otlp
export OTEL_LOGS_EXPORTER=none

export OTEL_EXPORTER_OTLP_TRACES_PROTOCOL=http/protobuf
export OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=\
http://otel-collector:4318/v1/traces

export OTEL_EXPORTER_OTLP_METRICS_PROTOCOL=http/protobuf
export OTEL_EXPORTER_OTLP_METRICS_ENDPOINT=\
http://prometheus:9090/api/v1/otlp/v1/metrics
```

The `OTEL_TRACES_EXPORTER` and `OTEL_METRICS_EXPORTER` selectors matter to
zero-code and auto-configured SDK distributions. They are unnecessary in the
code-based setup below because it constructs `OTLPSpanExporter` and
`OTLPMetricExporter` directly.

The Prometheus OTLP receiver is disabled by default and may be exposed without
authentication. Enable it only on an appropriately protected network or behind
an authenticated proxy. Direct OTLP export is useful for a small deployment,
an experiment, or a backend with a dedicated ingest endpoint. A Collector is
usually the better production boundary:

```text
application
  traces  ─┐
  metrics ─┼─> Collector ─> trace, metric, and log backends
  logs    ─┘
```

Central routing keeps backend credentials, retries, redaction, sampling, and
destination changes out of every application. If you split signals directly
from applications, make ownership of those concerns explicit.

## 🔄 Startup Order

Startup order is a common source of subtle bugs.

The important boundary is not merely module import. In a code-based setup, you
often import both the target library and its instrumentor before installing the
hook. The risky operations are creating long-lived clients, building a
framework's middleware stack, making startup calls, or starting background work
before providers and instrumentation are ready.

A reliable order is:

```text
process starts
  -> configure OTel providers
  -> install global client/logging instrumentation
  -> create the application
  -> instrument the application instance
  -> create long-lived clients and start background work
  -> serve traffic
```

Shutdown reverses the ownership order:

```text
stop accepting work
  -> stop background tasks
  -> close instrumented clients
  -> force-flush and shut down telemetry last
```

Make initialization and shutdown idempotent. A short-lived job or serverless
invocation must flush within its remaining execution budget, while a warm
runtime must not rebuild and shut down the provider on every invocation.
Exporter failures, queue pressure, and timeouts may drop telemetry, but must not
fail the business request.

### Bad: Application Work Happens Before Instrumentation

This module performs an HTTP warm-up and creates a long-lived client before OTel
is configured:

```python
# bad_app.py
import httpx
from fastapi import FastAPI
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

from observability import configure_otel


# This request has already finished before an OTel provider or HTTPX
# instrumentation exists, so it cannot produce the expected client span.
catalog_response = httpx.get(
    "https://model-registry.internal/models"
)
model_catalog = catalog_response.json()

# Whether an instrumentor can retrofit an already-created client is
# library- and version-specific. Do not make correctness depend on it.
downstream_client = httpx.AsyncClient(
    base_url="https://retrieval-service.internal"
)
app = FastAPI()

# Too late for the warm-up and potentially too late for objects or tasks
# whose hooks were fixed when they were created.
configure_otel()
HTTPXClientInstrumentor().instrument()
FastAPIInstrumentor.instrument_app(app)
```

Problems with this shape:

- the warm-up request is definitely absent from traces;
- its propagation headers were never injected;
- existing clients may or may not be retrofitted, depending on the
  instrumentation implementation;
- any background task started above `configure_otel()` would capture the same
  uninstrumented state;
- module import now performs network I/O, which also makes tests and reloaders
  harder to control;
- the client and providers have no coordinated shutdown path.

Another common mistake is calling `FastAPIInstrumentor.instrument_app(app)`
inside the FastAPI lifespan. Lifespan runs after the server has started the
application; that is too late to safely add instrumentation middleware and may
raise a middleware-stack error.

> ⚠️ **Watch out:** Never call `FastAPIInstrumentor.instrument_app(app)` inside the lifespan — the server's middleware stack is already frozen by that point and the call will fail or silently have no effect.

### Good: Instrument First, Create Runtime Clients In Lifespan

Configure providers at module startup, install global hooks, create and
instrument the FastAPI instance, and let the lifespan own long-lived runtime
clients:

```python
# app.py
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.logging import LoggingInstrumentor

from observability import configure_otel, shutdown_otel


# 1. Providers exist before any instrumented work starts.
configure_otel()

# 2. Install process-wide library hooks before creating clients.
HTTPXClientInstrumentor().instrument()
LoggingInstrumentor().instrument(set_logging_format=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 3. This client is created after HTTPX instrumentation is active.
    app.state.retrieval_client = httpx.AsyncClient(
        base_url="https://retrieval-service.internal",
        timeout=5.0,
    )
    try:
        # Start background tasks here as well, after instrumentation.
        yield
    finally:
        # 4. Stop work and close clients while telemetry is still active.
        await app.state.retrieval_client.aclose()

        # 5. Flush and shut down providers last.
        shutdown_otel()


# The app must exist before instance-level FastAPI instrumentation can
# attach middleware, but instrumentation still happens before serving.
app = FastAPI(lifespan=lifespan)
FastAPIInstrumentor.instrument_app(app)


@app.get("/documents/{document_id}")
async def get_document(document_id: str, request: Request) -> dict:
    response = await request.app.state.retrieval_client.get(
        f"/documents/{document_id}"
    )
    response.raise_for_status()
    return response.json()
```

This produces the intended ordering:

```text
module import
  configure providers
  install HTTPX and logging hooks
  create FastAPI app
  attach FastAPI instrumentation

application startup
  create instrumented AsyncClient
  start background tasks

application shutdown
  stop background tasks
  close AsyncClient
  flush and shut down OTel providers
```

Closing application resources before OTel matters. A client's `close()` call
or a worker's final operation may finish spans; shutting down the providers
first can discard that final telemetry.

> 💡 **Key insight:** Shut down application clients and workers before calling `shutdown_otel()` — a client's close or a worker's final message may still be finishing spans when providers go down, and those spans vanish silently.

### Acceptable: A Module-Level Client Created In The Right Order

Lifespan ownership is usually clearer, but a module-level client can still be
correct when the library supports it and shutdown is explicit. Using the same
imports as the previous example:

```python
configure_otel()
HTTPXClientInstrumentor().instrument()

downstream_client = httpx.AsyncClient(
    base_url="https://retrieval-service.internal"
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        yield
    finally:
        await downstream_client.aclose()
        shutdown_otel()


app = FastAPI(lifespan=lifespan)
FastAPIInstrumentor.instrument_app(app)
```

The important fact is that `downstream_client` is constructed after the HTTPX
instrumentor is active, and is closed before OTel shuts down.

### Zero-Code Owns The Early Setup

With `opentelemetry-instrument`, the launcher configures the SDK and installs
instrumentation before importing `app:app`:

```bash
OTEL_SERVICE_NAME=chat-api \
OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4318 \
opentelemetry-instrument uvicorn app:app
```

In that mode, do not also call `configure_otel()` or process-wide
`instrument()` methods in application code. The application should own its
clients and lifespan cleanup; the launcher owns provider and auto-
instrumentation setup.

## 🛠️ Configure Traces And Metrics

Create one startup module. Keep it idempotent so tests, reloaders, or worker
forks do not configure providers twice.

```python
# observability.py
from __future__ import annotations

import os
from uuid import uuid4
from dataclasses import dataclass

from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor


@dataclass(slots=True)
class OtelHandles:
    tracer_provider: TracerProvider
    meter_provider: MeterProvider


_otel_handles: OtelHandles | None = None
_otel_shutdown = False
_instance_id = str(uuid4())


def configure_otel() -> OtelHandles:
    global _otel_handles

    if _otel_shutdown:
        raise RuntimeError("OTel shutdown is terminal; start a new process")
    if _otel_handles is not None:
        return _otel_handles

    resource = Resource.create(
        {
            "service.name": os.environ["OTEL_SERVICE_NAME"],
            "service.version": os.getenv("SERVICE_VERSION", "unknown"),
            "service.instance.id": _instance_id,
            "deployment.environment.name": os.getenv("ENVIRONMENT", "development"),
        }
    )

    otlp_base = os.getenv(
        "OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318"
    ).rstrip("/")
    traces_endpoint = os.getenv(
        "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT",
        f"{otlp_base}/v1/traces",
    )
    metrics_endpoint = os.getenv(
        "OTEL_EXPORTER_OTLP_METRICS_ENDPOINT",
        f"{otlp_base}/v1/metrics",
    )

    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(
        BatchSpanProcessor(
            OTLPSpanExporter(endpoint=traces_endpoint),
            max_queue_size=2048,
            max_export_batch_size=512,
            schedule_delay_millis=5000,
            export_timeout_millis=30000,
        )
    )
    trace.set_tracer_provider(tracer_provider)

    metric_reader = PeriodicExportingMetricReader(
        OTLPMetricExporter(endpoint=metrics_endpoint),
        export_interval_millis=15000,
        export_timeout_millis=30000,
    )
    meter_provider = MeterProvider(
        resource=resource,
        metric_readers=[metric_reader],
    )
    metrics.set_meter_provider(meter_provider)

    _otel_handles = OtelHandles(
        tracer_provider=tracer_provider,
        meter_provider=meter_provider,
    )

    return _otel_handles


def shutdown_otel() -> None:
    global _otel_handles, _otel_shutdown

    if _otel_handles is None:
        return

    handles = _otel_handles
    _otel_handles = None
    _otel_shutdown = True
    try:
        handles.tracer_provider.shutdown()
    finally:
        handles.meter_provider.shutdown()
```

What this does:

- `Resource.create(...)` attaches service identity to all emitted telemetry.
- `TracerProvider` creates tracers and owns trace sampling/export behavior.
- `BatchSpanProcessor` buffers spans and exports them in batches.
- `OTLPSpanExporter` sends spans to the configured trace destination.
- `MeterProvider` creates meters and owns metric aggregation/export behavior.
- `PeriodicExportingMetricReader` collects aggregated metrics on an interval.
- `OTLPMetricExporter` sends metric batches to the configured metrics destination.
- Signal-specific endpoint variables override the normalized global base and
  are passed through unchanged. Only the global base is normalized before the
  code appends `/v1/traces` or `/v1/metrics`.
- `shutdown_otel()` clears handles and marks shutdown terminal. Repeated shutdown is a no-op; configure after shutdown raises because Python global providers cannot be replaced. Test a fresh lifecycle in another process. Configure once per worker **after** a prefork server forks, rather than inheriting exporter threads. The per-process UUID is shared across signal resources. This guide invokes it explicitly from the FastAPI lifespan or a script `finally` block rather than also registering `atexit`.

## 🔌 Add Auto-Instrumentation

Use instrumentation libraries for framework and library telemetry. They handle
server spans, client spans, propagation, and common semantic attributes.

```python
# app.py
from contextlib import asynccontextmanager

from fastapi import FastAPI
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.logging import LoggingInstrumentor

from observability import configure_otel, shutdown_otel

configure_otel()

HTTPXClientInstrumentor().instrument()
LoggingInstrumentor().instrument(set_logging_format=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    shutdown_otel()


app = FastAPI(lifespan=lifespan)
FastAPIInstrumentor.instrument_app(app)
```

What you get:

| Instrumentation | Creates |
| --- | --- |
| FastAPI | HTTP server spans, route attributes, context extraction. |
| HTTPX | HTTP client spans, context injection. |
| Logging | Trace ID and span ID fields on log records created inside spans. |

If an HTTP client is instrumented, it usually injects `traceparent` and baggage
headers automatically. If the server framework is instrumented, it usually
extracts incoming trace context automatically.

Manual propagation is still useful for queues, custom transports, tests, and
places where you want exact control. See [04_multi_service_examples.md](04_multi_service_examples.md).

## 🛠️ Add Manual Spans

Auto-instrumentation knows framework calls. It does not know your business
steps. Add manual spans around operations that explain latency, errors, or
behavior.

```python
from opentelemetry import trace
tracer = trace.get_tracer(__name__)


def retrieve_documents(query: str, top_k: int) -> list[dict]:
    with tracer.start_as_current_span(
        "rag.retrieve",
        # Prevent the context manager from creating a legacy span event.
        record_exception=False,
    ) as span:
        span.set_attribute("rag.retrieval.strategy", "hybrid")
        span.set_attribute("rag.top_k", top_k)

        try:
            docs = vector_store.search(query=query, top_k=top_k)
        except Exception as exc:
            span.set_attribute("error.type", type(exc).__name__)
            raise

        span.set_attribute("rag.retrieved_documents", len(docs))
        return docs
```

Span design rules:

| Rule | Example |
| --- | --- |
| Use stable names. | `rag.retrieve`, not `retrieve user 123`. |
| Put bounded facts in attributes. | `rag.top_k=5`, `rag.retrieval.strategy=hybrid`. |
| Record failures without span events. | Pass `record_exception=False`, add low-cardinality `error.type`, and re-raise so the context manager still sets `ERROR`; emit exception details as a correlated log-based event at the owning logging boundary. |
| Avoid sensitive content. | Do not store raw prompts, documents, access tokens, or emails. |
| Use semantic conventions where possible. | `http.route`, `gen_ai.request.model`, `db.system.name`. |

Use `trace.get_current_span()` when you only need to enrich the active span:

```python
from opentelemetry import trace


def attach_request_context(tenant_tier: str) -> None:
    span = trace.get_current_span()
    if span.is_recording():
        span.set_attribute("app.tenant.tier", tenant_tier)
```

## 📊 Add Custom Metrics

Create instruments once, usually at module load time. Record measurements in
request paths with low-cardinality attributes.

```python
import time
from contextlib import contextmanager
from collections.abc import Iterator

from opentelemetry import metrics

meter = metrics.get_meter(__name__)

llm_requests = meter.create_counter(
    "llm.requests",
    unit="{request}",
    description="Number of LLM requests attempted.",
)

llm_tokens = meter.create_counter(
    "llm.tokens",
    unit="{token}",
    description="Tokens used by LLM calls.",
)

llm_duration = meter.create_histogram(
    "llm.request.duration",
    unit="s",
    description="End-to-end LLM request duration.",
)

llm_inflight = meter.create_up_down_counter(
    "llm.inflight",
    unit="{request}",
    description="LLM requests currently in progress.",
)


@contextmanager
def measure_llm_call(*, provider: str, model: str, route: str) -> Iterator[None]:
    attributes = {
        "gen_ai.provider.name": provider,
        "gen_ai.request.model": model,
        "http.route": route,
    }

    llm_inflight.add(1, attributes)
    start = time.perf_counter()
    outcome = "success"

    try:
        yield
    except Exception:
        outcome = "error"
        raise
    finally:
        duration = time.perf_counter() - start
        metric_attrs = {**attributes, "app.outcome": outcome}
        llm_requests.add(1, metric_attrs)
        llm_duration.record(duration, metric_attrs)
        llm_inflight.add(-1, attributes)
```

Record token usage after the provider returns:

```python
def record_usage(
    provider: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
) -> None:
    base = {"gen_ai.provider.name": provider, "gen_ai.request.model": model}
    llm_tokens.add(input_tokens, {**base, "gen_ai.token.type": "input"})
    llm_tokens.add(output_tokens, {**base, "gen_ai.token.type": "output"})
```

Metric attribute rules:

| Good | Bad |
| --- | --- |
| model | prompt text |
| provider | user email |
| route template | raw URL |
| outcome enum | exception message |
| tenant tier | tenant ID if many tenants |

Traces can tolerate some high-cardinality searchable data if the backend and
privacy model allow it. Metrics usually cannot. Metric attributes create time
series, so be strict.

## 📊 Observable Gauges

Use an observable gauge when the value is read at collection time rather than
recorded inline.

```python
from opentelemetry import metrics

meter = metrics.get_meter(__name__)


def observe_queue_depth(options):
    depth = queue_client.depth("llm-jobs")
    yield metrics.Observation(depth, {"queue.name": "llm-jobs"})


meter.create_observable_gauge(
    "worker.queue.depth",
    callbacks=[observe_queue_depth],
    unit="{job}",
    description="Jobs waiting in the worker queue.",
)
```

The callback runs when the SDK collects metrics. Keep it fast and reliable. Do
not call slow or fragile dependencies in gauge callbacks unless you can tolerate
collection failures.

## 🔗 Correlate Logs With Traces

OpenTelemetry log correlation is different from OTel log export.

| Capability | Meaning |
| --- | --- |
| Trace-log correlation | Normal Python logs include `trace_id` and `span_id` while a span is active. |
| OTel log export | Log records flow through an OpenTelemetry log pipeline. |

For Python, trace-log correlation is the most common starting point.

```python
import logging

logger = logging.getLogger(__name__)


def build_prompt(question: str, docs: list[dict]) -> str:
    logger.info("building prompt", extra={"document_count": len(docs)})
    return render_prompt(question=question, docs=docs)
```

With `LoggingInstrumentor().instrument(set_logging_format=True)`, records
created inside an active span can include trace and span identifiers. In
production, many teams use structured JSON logging and add those fields to their
formatter instead of using the default OTel logging format.

### Structlog Correlation When Logs Stay On Stdout

`structlog` does not need to pass through Python's standard-library formatter.
If stdout or a file agent remains the log transport, add the active trace
context in the processor chain:

```python
import structlog
from opentelemetry import trace
from opentelemetry.trace import format_span_id, format_trace_id


def add_otel_trace_context(_, __, event_dict):
    context = trace.get_current_span().get_span_context()
    if context.is_valid:
        event_dict["trace_id"] = format_trace_id(context.trace_id)
        event_dict["span_id"] = format_span_id(context.span_id)
        event_dict["trace_sampled"] = context.trace_flags.sampled
    return event_dict


structlog.configure(
    processors=[
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        add_otel_trace_context,
        structlog.processors.JSONRenderer(),
    ]
)

log = structlog.get_logger("chat-api").bind(
    **{"service.name": "chat-api"}
)

with tracer.start_as_current_span("rag.retrieve"):
    log.info("retrieval completed", **{"rag.returned_documents": 5})
```

The JSON line should contain 32 lowercase hex characters in `trace_id` and 16
in `span_id`. If the fields are missing, the call happened outside an active
span or a renderer ran before `add_otel_trace_context`. This processor provides
correlation only: it does not create an OTel logs pipeline.

Most operational logs need the first three fields below. Add the others only
when they are bounded, safe, and useful:

- **`trace_id`**;
- **`span_id`**;
- **`service.name`**;
- `event_name` for a named OTel event, not as a substitute for the message;
- bounded request context such as route, model, provider, outcome;
- local error details and stack traces.

Bad log fields:

- raw prompts;
- full request bodies;
- access tokens;
- cookies;
- retrieved document text;
- personal data unless explicitly permitted.

## 📤 Optional OTel Log Export

The OTel logs signal is stable in the specification, but Python log API/SDK
support is still listed as Development in the language status. Treat Python log
export as an evolving area and validate it carefully before standardizing on it.

Instrumentations will migrate exceptions gradually. When an installed
instrumentation implements the
[exception signal transition](https://opentelemetry.io/docs/specs/semconv/exceptions/exceptions-logs/),
use
`OTEL_SEMCONV_EXCEPTION_SIGNAL_OPT_IN=logs` to request log-only exception
events. `logs/dup` emits both representations for a temporary compatibility
test, but doubles volume and sensitive-data exposure. Unsupported
instrumentations ignore the setting, so verify the exported signals after every
upgrade rather than assuming the variable changed their behavior.

If you do use OTel log export, keep it separate in your mental model:

```text
Python logging
  -> logging bridge or handler
  -> LoggerProvider
  -> log processor
  -> log exporter
  -> Collector logs pipeline
  -> log backend
```

For many Python services, this is enough:

```text
structured application logs -> log agent/backend
trace and span IDs in log fields -> correlation with traces
```

### Emit Named Log-Based Events Through Structlog

A correlated JSON log is not automatically an OpenTelemetry **Event**. In the
[OTel data model](https://opentelemetry.io/docs/specs/otel/logs/data-model/), an
Event is a `LogRecord` whose top-level `event_name` is non-empty. Do not emulate
that field with an `event.name` attribute; backends and compatibility transforms
may not recognize it as an Event.

Python 1.44 supports `event_name` on `Logger.emit()`. The official
[`opentelemetry-instrumentation-structlog`](https://github.com/open-telemetry/opentelemetry-python-contrib/tree/main/instrumentation/opentelemetry-instrumentation-structlog)
package can export ordinary structlog calls as correlated OTel logs. In its
initial `0.65b0` release, however, it maps structlog's `event` value to the log
body and does not populate the top-level OTel `event_name`. Use the small
processor below when the record must be a true named Event.

Install compatible packages together:

```bash
pip install \
  'opentelemetry-api>=1.44,<2' \
  'opentelemetry-sdk>=1.44,<2' \
  'opentelemetry-exporter-otlp-proto-http>=1.44,<2' \
  'structlog>=25,<26'
```

This baseline exports named events to the console so the result is visible. It
assumes tracing already uses the same `resource` and `tracer` created earlier
in this chapter:

```python
from time import time_ns
from typing import Any

import structlog
from opentelemetry._logs import SeverityNumber, get_logger, set_logger_provider
from opentelemetry.context import get_current
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import (
    ConsoleLogRecordExporter,
    SimpleLogRecordProcessor,
)


logger_provider = LoggerProvider(resource=resource)
logger_provider.add_log_record_processor(
    SimpleLogRecordProcessor(ConsoleLogRecordExporter())
)
set_logger_provider(logger_provider)


class OtelEventProcessor:
    """Turn selected structlog calls into named OTel LogRecords."""

    _severity = {
        "debug": SeverityNumber.DEBUG,
        "info": SeverityNumber.INFO,
        "warning": SeverityNumber.WARN,
        "error": SeverityNumber.ERROR,
        "critical": SeverityNumber.FATAL,
    }
    _severity_text = {
        "warning": "WARN",
        "critical": "FATAL",
    }

    def __init__(self, provider: LoggerProvider) -> None:
        self._logger = get_logger(
            "chat-api.events", logger_provider=provider
        )

    def __call__(
        self,
        _logger: Any,
        method_name: str,
        event_dict: dict[str, Any],
    ) -> dict[str, Any]:
        event_name = event_dict.pop("otel_event_name", None)
        if event_name is None:
            return event_dict

        level = str(event_dict.get("level", method_name)).lower()
        attributes = {
            key: value
            for key, value in event_dict.items()
            if key not in {"event", "level", "timestamp", "exception"}
        }
        if "exception" in event_dict:
            attributes["exception.stacktrace"] = event_dict["exception"]

        self._logger.emit(
            # Events require the occurrence time, not only observed time.
            timestamp=time_ns(),
            event_name=str(event_name),
            body=event_dict.get("event"),
            severity_number=self._severity.get(
                level, SeverityNumber.INFO
            ),
            severity_text=self._severity_text.get(level, level.upper()),
            attributes=attributes,
            # This is what attaches trace_id, span_id, and trace flags.
            context=get_current(),
        )

        # The named event already entered the OTel pipeline. Do not also emit
        # it to stdout, where a log agent could ingest a duplicate.
        raise structlog.DropEvent


structlog.configure(
    processors=[
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.format_exc_info,
        OtelEventProcessor(logger_provider),
        add_otel_trace_context,
        structlog.processors.JSONRenderer(),
    ]
)

log = structlog.get_logger("chat-api")

with tracer.start_as_current_span(
    "provider.request", record_exception=False
) as span:
    try:
        call_provider()
    except TimeoutError as exc:
        span.set_attribute("error.type", type(exc).__name__)
        log.error(
            "provider request timed out",
            otel_event_name="app.provider.request.exception",
            exc_info=True,
            **{
                "error.type": type(exc).__name__,
                "exception.type": type(exc).__qualname__,
                "server.address": "provider.example.com",
            },
        )
        raise
```

The console exporter should show one log record with
`event_name=app.provider.request.exception` and non-zero `trace_id` and
`span_id`. If `event_name` is empty, the call bypassed this processor. If the IDs
are zero, it ran outside the span's active context.

For production, construct the provider with batching and OTLP/HTTP instead of
adding the console processor:

```python
from opentelemetry._logs import set_logger_provider
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor

logger_provider = LoggerProvider(resource=resource)
logger_provider.add_log_record_processor(
    BatchLogRecordProcessor(OTLPLogExporter())
)
set_logger_provider(logger_provider)
```

Configure the provider once at startup and call `logger_provider.shutdown()`
on process shutdown. The `DropEvent` is deliberate: if you want both direct
OTLP and stdout copies, remove it only after confirming that stdout is not also
collected into the same backend. Otherwise every named event appears twice.

Route this exporter to a logs backend or to the Collector's logs pipeline. The
[Langfuse OTLP endpoint](https://langfuse.com/integrations/native/opentelemetry)
currently ingests traces, not the OTel logs signal, so it is not a destination
for these log-based events. If the same occurrence must appear as a Langfuse
`event` observation, create that observation through the Langfuse SDK as a
separate product-observability decision.

Use this mechanism for checkpoints, state changes, and exceptions that need a
stable schema and their own timestamp. Use an ordinary structlog record for
free-form diagnostics, and a span attribute for a fact that describes the
whole operation. Event names must be stable; put request IDs, user IDs, model
names, and other varying values in attributes.

## 🔌 Zero-Code Instrumentation

Zero-code instrumentation removes framework instrumentor calls and most SDK
setup from application code. Two commands have different jobs:

- `opentelemetry-bootstrap` inspects packages in the active Python environment
  and recommends or installs matching `opentelemetry-instrumentation-*`
  packages.
- `opentelemetry-instrument` configures the SDK from CLI options and environment
  variables, discovers the installed instrumentors, and applies their runtime
  hooks before starting the application command.

Typical setup:

```bash
pip install opentelemetry-distro \
  opentelemetry-exporter-otlp-proto-http

opentelemetry-bootstrap -a install
```

Running `opentelemetry-bootstrap` without arguments only prints the recommended
instrumentation packages. `-a install` installs them. The launcher does not
contain every FastAPI, HTTPX, SQLAlchemy, or Redis integration itself; the
corresponding instrumentation package must exist in the environment.

The practical difference is:

| Concern | Programmatic setup | Zero-code launcher |
| --- | --- | --- |
| Provider and exporters | Python startup code constructs them. | Distro and environment variables configure them. |
| Framework and client hooks | Code calls `FastAPIInstrumentor.instrument_app(app)`, `HTTPXClientInstrumentor().instrument()`, and similar methods. | Installed instrumentors are discovered and activated automatically. |
| Instrumentation dependencies | Install each integration explicitly. | `opentelemetry-bootstrap -a install` can discover and install matching integrations. |
| Custom processors and metric views | Direct control in Python. | Limited to what the distro and declarative configuration expose. |
| Business spans and metrics | Written with the OTel API. | Still written with the OTel API; zero-code cannot infer `rag.retrieve` or other domain operations. |

Run:

```bash
OTEL_SERVICE_NAME=chat-api \
OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4318 \
OTEL_TRACES_EXPORTER=otlp \
OTEL_METRICS_EXPORTER=otlp \
OTEL_LOGS_EXPORTER=none \
opentelemetry-instrument uvicorn app:app --host 0.0.0.0 --port 8000
```

With the appropriate packages installed, this can create inbound FastAPI server
spans, outbound HTTP client spans, SQLAlchemy database spans, and Redis client
spans without calls such as `FastAPIInstrumentor.instrument_app(app)` in
`app.py`.

Auto-instrumentation is composed per installed instrumentation package. The
FastAPI/ASGI instrumentation owns the inbound HTTP boundary: it extracts HTTP
trace context and creates server spans. It does not also instrument SQS, Kafka,
or another transport merely because the HTTP handler publishes a message.
Queue injection, extraction, and consumer spans come from that queue library's
instrumentation package, when one is installed and enabled.

Disable an installed integration without uninstalling its package by using its
instrumentor entry-point name:

```bash
OTEL_PYTHON_DISABLED_INSTRUMENTATIONS=urllib3,redis \
opentelemetry-instrument uvicorn app:app
```

The values are instrumentor entry-point names, not necessarily package-name
suffixes. For example,
[`opentelemetry-instrumentation-boto3sqs==0.65b0`](https://github.com/open-telemetry/opentelemetry-python-contrib/blob/v0.65b0/instrumentation/opentelemetry-instrumentation-boto3sqs/pyproject.toml)
registers as `boto3`:

```bash
OTEL_PYTHON_DISABLED_INSTRUMENTATIONS=boto3 \
opentelemetry-instrument python worker.py
```

This disables that whole entry point in this process, not only its consumer
side. It is appropriate for a worker that will manually own its SQS receive and
process spans. If one process must keep automatic producer hooks but customize
only consumer semantics, use the instrumentation's programmatic controls when
they support that split; otherwise own both queue directions manually. FastAPI,
HTTPX, and SQLAlchemy remain automatic because their entry points are still
enabled.

Do not normally activate the same integration both ways. Launching with
`opentelemetry-instrument` while application code also calls that integration's
`.instrument()` or `.instrument_app()` method can produce warnings, duplicate
hooks, or duplicate spans. Manual business spans are different: they use the
provider configured by the launcher and should remain in application code.

For reproducible deployments, run bootstrap while resolving or building the
environment, then lock the resulting instrumentation packages. Do not let each
container startup discover and install a potentially different dependency set.

Use zero-code when you want broad automatic coverage quickly. Use code-based
setup when you need precise provider configuration, custom processors, explicit
metric views, or controlled shutdown.

> 💡 **Key insight:** Zero-code gives framework coverage for free, but it cannot create `rag.retrieve`, `agent.plan`, or any business-domain span — those always need manual instrumentation in application code.

## 🔄 Background Workers And Queues

Workers need the same provider setup as web services:

```text
worker starts
  -> configure OTel
  -> instrument queue/client libraries
  -> read the message carrier from headers or attributes
  -> extract context from that carrier
  -> create consumer/process spans
  -> flush on shutdown
```

For long-running workers, configure once at process startup. For short-lived
jobs, flush in `finally`.

Choose the trace relationship before writing the handler:

| Queue lifecycle | Parent of the consumer span | Use when |
| --- | --- | --- |
| Continued trace | Extracted producer context | One message continues the same causal operation and the resulting long trace is useful. |
| New trace plus link | Empty context; extracted producer context becomes a `Link` | Work is delayed, independently retried, batched, fan-in/fan-out, or owned by a separate lifecycle. |

For a continued trace, use the extracted context as parent:

```python
from opentelemetry import trace
from opentelemetry.propagate import extract


def handle_message(message) -> None:
    carrier = message.headers
    ctx = extract(carrier)
    with tracer.start_as_current_span(
        "worker.process_message",
        context=ctx,
        kind=trace.SpanKind.CONSUMER,
    ):
        process(message.payload)
```

For a separate worker lifecycle, extract the same carrier but use it only as a
link:

```python
from opentelemetry import context as otel_context, trace
from opentelemetry.propagate import extract
from opentelemetry.trace import Link


def handle_message(message) -> None:
    carrier = message.headers
    incoming_ctx = extract(carrier)
    producer_ctx = trace.get_current_span(
        incoming_ctx
    ).get_span_context()
    links = [Link(producer_ctx)] if producer_ctx.is_valid else []

    with tracer.start_as_current_span(
        "worker.process_message",
        # `None` means "use current context", not "create a root".
        context=otel_context.Context(),
        kind=trace.SpanKind.CONSUMER,
        links=links,
    ):
        process(message.payload)
```

Success is structural: the worker span has a new `trace_id`, no
`parent_span_id`, and one valid link to the producer span. If it shares the
producer trace ID, the extracted or current context became its parent. If an
automatic consumer span also appears, manual root creation did not undo it;
both the instrumentation and the handler currently own the boundary.

The generic examples above use `message.headers` as the transport field, then
name its contents `carrier`. They assume a string-to-string carrier. Boto3 SQS
stores propagated fields inside nested `MessageAttributes`, so its carrier
adapter is required even when the automatic hooks are disabled:

```python
from opentelemetry import propagate
from opentelemetry.instrumentation.boto3sqs import (
    Boto3SQSGetter,
    Boto3SQSSetter,
)


incoming_ctx = propagate.extract(
    message.get("MessageAttributes", {}),
    getter=Boto3SQSGetter(),
)

outgoing_attributes: dict = {}
propagate.inject(outgoing_attributes, setter=Boto3SQSSetter())
sqs.send_message(
    QueueUrl=queue_url,
    MessageBody=body,
    MessageAttributes=outgoing_attributes,
)
```

The getter and setter only adapt the carrier representation; importing them
does not enable automatic spans. Inject while the intended producer span is
current, and use `incoming_ctx` only as a link when starting the empty-context
consumer span. When polling manually, pass
`MessageAttributeNames=list(propagate.get_global_textmap().fields)` to
`receive_message()`; otherwise SQS does not return the propagated fields and the
consumer silently produces no link.

Queue instrumentation behavior is library- and version-specific. In
`opentelemetry-instrumentation-boto3sqs==0.65b0`, `ReceiveMessage` creates a
`CONSUMER` receive span; each processing span is its child, links to the
extracted producer context, and becomes current while that message is iterated:

```text
Trace B
SQS receive                         CONSUMER, root
└── SQS process                     CONSUMER, link -> producer in Trace A
```

That is already a new worker trace with a causal link, but it is not identical
to a single root `process` span. If that extra receive/process hierarchy is
acceptable, use the automatic spans and do not add another consumer span. If
you require `process` itself to be the root, disable the `boto3` instrumentor in
the worker and use the manual boundary above. Recheck the emitted shape when
upgrading; other queue integrations expose different semantics and controls.

## 🔄 CLI Jobs And Batch Scripts

Short-lived programs often lose telemetry because the process exits before the
batch processor exports.

```python
from observability import configure_otel, shutdown_otel


def main() -> None:
    configure_otel()
    try:
        run_batch()
    finally:
        shutdown_otel()


if __name__ == "__main__":
    main()
```

For scripts, consider a shorter batch delay or explicit shutdown after the work
finishes. Console exporters are useful while developing a job locally.

## 🛠️ Tests

Avoid exporting telemetry to real backends from unit tests. Use one of these
patterns:

| Test type | Pattern |
| --- | --- |
| Unit test | Do not configure the SDK, or use in-memory exporters. |
| Integration test | Export to a local Collector or in-memory exporter. |
| Trace shape test | Assert span names, attributes, and parent-child relationships. |
| Metrics test | Assert recorded measurements or exported points with bounded attributes. |

If your production setup module registers global providers, make tests
idempotent and isolated. Global OTel state is process-wide, so test suites can
interfere with themselves if they repeatedly configure providers.

## Reproduce process ownership in isolation

The [bootstrap test](../examples/local/verify_bootstrap.py) executes the exact startup module shown above in two fresh interpreters. From the repository root, run:

```bash
python examples/local/verify_bootstrap.py
```

It checks repeated configuration returns the same handles, repeated shutdown is harmless, reconfiguration after terminal shutdown raises, resources share one per-process identity, and two independent processes receive different instance IDs. It does not certify exporter/backend delivery. This avoids replacing Python global providers inside one test process, which is not a supported lifecycle.

## 🔍 Troubleshooting Python Telemetry

No spans:

- Did `configure_otel()` run before the app served requests?
- Is the correct exporter package installed?
- Is `OTEL_SERVICE_NAME` set?
- Is the Collector reachable from the app container?
- Is the trace pipeline enabled in the Collector?
- Is sampling dropping the trace?

Duplicate spans:

- Are you using both zero-code and code-based setup?
- Did a dev reloader configure instrumentation twice?
- Did tests import the app repeatedly without idempotent setup?
- Did you call `HTTPXClientInstrumentor().instrument()` more than once?

Broken traces across services:

- Is the outgoing client instrumented?
- Is the receiving framework instrumented?
- Are `traceparent` headers preserved by proxies?
- Are both services using `tracecontext` propagator?
- Is context lost when work moves to a thread, task, or queue?
- Does the worker intentionally continue the producer trace or start a linked
  trace, and does the emitted parent/link shape match that policy?
- Do automatic and manual instrumentation both create a consumer span for the
  same message?

Missing metrics:

- Is `MeterProvider` configured?
- Is there a metric reader?
- Is the metrics exporter endpoint correct?
- Does the Collector have a metrics pipeline?
- Is your backend renaming metric names or labels?

Logs not correlated:

- Is logging instrumentation enabled before logs are emitted?
- Are logs created while a span is active?
- Does your formatter include trace and span fields?
- Does the log backend parse those fields?

Named log events look like ordinary logs or appear twice:

- Is top-level OTel `event_name` populated, rather than only an `event.name` attribute?
- Does `OtelEventProcessor` run before the renderer?
- Are both direct OTLP export and stdout collection ingesting the same record?

## ⚠️ Common Python Pitfalls

- Configuring the SDK after importing or creating framework clients.
- Creating a new `TracerProvider` in every module.
- Calling instrumentors repeatedly in reloaders or tests.
- Treating `context=None` as an instruction to create a root span; it reuses
  the current context.
- Creating a manual queue-consumer span while an automatic instrumentor already
  owns the same processing boundary.
- Using `SimpleSpanProcessor` in production request paths.
- Emitting metrics with high-cardinality attributes.
- Putting raw prompts, request bodies, document contents, emails, or secrets in attributes.
- Expecting baggage to automatically appear as span attributes.
- Using only sampled traces for alerting totals.
- Forgetting to flush in CLI jobs, subprocesses, serverless handlers, and workers.
- Expecting `/v1/traces` or `/v1/metrics` to be appended to a signal-specific
  OTLP/HTTP endpoint.
- Appending OTLP/HTTP signal paths to an OTLP/gRPC target.
- Assuming Python OTel log export has the same maturity as trace-log correlation.
- Using an `event.name` attribute instead of the top-level LogRecord `event_name`.
- Exporting the same structlog event directly over OTLP and through a stdout log agent.

## ✅ Minimal Production Checklist

- `service.name`, `service.version`, instance ID, and environment are set.
- Providers are configured once at process startup.
- Framework and client instrumentations are installed before clients are created.
- All services use compatible propagators.
- Each queue boundary has an explicit parent-or-link policy, verified from an
  exported trace using the deployed instrumentation version.
- Manual spans cover business operations, not every small helper function.
- Metrics use bounded attributes and are emitted independently from traces.
- Logs include trace and span IDs.
- Exporters normally send to a Collector. Any direct per-signal backend routes
  have explicit owners for credentials, retries, policy, and destination
  changes.
- Shutdown flushes telemetry in web apps, workers, jobs, and serverless handlers.
- Tests do not leak telemetry to production backends.

## Recap

- Configure providers before serving so framework spans have a recorder.
- FastAPI owns HTTP semantics; manual spans add retrieval meaning under current context.
- Export destination changes do not change parentage.
- Measurements aggregate independently of trace sampling and export.
- Close clients and flush last; provider shutdown is terminal in a process.

## Check yourself

**A request succeeds while OTLP logs connection errors. Was the business operation lost?**

<details><summary>Answer</summary>

The successful response proves the operation ran. Export failures affect telemetry delivery; inspect receiver reachability and send a fresh canary after recovery. Missing traces cannot prove missing business work.

</details>

**Two workers share HOSTNAME. Can it identify both service instances?**

<details><summary>Answer</summary>

No. Each worker is a separate runtime with its own telemetry lifecycle. A process UUID distinguishes them, while service.name stays identical for aggregation.

</details>

## Try it

Add a second local operation `prompt.build` after retrieval, using the existing tracer. Predict its parent before running. Hint: the retrieval context has ended, but the SERVER context is still current.

<details><summary>Worked solution</summary>

Open `with tracer.start_as_current_span("prompt.build", record_exception=False):` after the retrieval block and perform the fake prompt construction inside. Both business spans share the server parent; prompt.build is a sibling, not a retrieval child. Confirm parent IDs in console output.

</details>
