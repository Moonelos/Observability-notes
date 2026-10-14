# OpenTelemetry and Langfuse Examples

Last checked against the Langfuse and OpenTelemetry documentation on 2026-07-20.

These examples show how to combine OpenTelemetry and Langfuse in real LLM and agent systems.

Read the concept guides first:

- [../opentelemetry/README.md](../opentelemetry/README.md)
- [../langfuse/README.md](../langfuse/README.md)

Then use these examples as implementation templates.

| File | Scenario | Bootstrap profile |
| --- | --- | --- |
| [01_rag_with_otel_and_langfuse.md](01_rag_with_otel_and_langfuse.md) | Single-service RAG with Langfuse traces and OpenTelemetry metrics | Direct SDK tracing |
| [02_multi_service_agent.md](02_multi_service_agent.md) | Gateway calling a bounded tool-using agent | Direct SDK tracing in both services |
| [03_collector_prometheus_langfuse.md](03_collector_prometheus_langfuse.md) | Collector routing to Langfuse and Prometheus-compatible metrics | Centralized Collector export |

## 🛠️ Install

The examples use Python 3.11 or later. These ranges keep the APIs used here compatible while allowing patch and minor security updates:

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install \
  'langfuse>=4.14,<5' \
  'openai>=1.92,<3' \
  'fastapi>=0.115,<1' \
  'uvicorn[standard]>=0.30,<1' \
  'httpx>=0.27,<1' \
  'pydantic>=2.8,<3' \
  'opentelemetry-api>=1.39,<2' \
  'opentelemetry-sdk>=1.39,<2' \
  'opentelemetry-exporter-otlp-proto-http>=1.39,<2' \
  'opentelemetry-exporter-otlp-proto-grpc>=1.39,<2' \
  'opentelemetry-instrumentation-fastapi>=0.60b0,<1' \
  'opentelemetry-instrumentation-httpx>=0.60b0,<1'
python -c 'import fastapi, httpx, langfuse, openai, opentelemetry.sdk'
```

Lock the resolved versions in the application rather than resolving this range during every deployment. OpenTelemetry stable packages and beta instrumentation packages are released as matched sets: SDK `1.39.x` corresponds to instrumentation `0.60b0`, for example. Upgrade them together and run the smoke request for the relevant example.

> 💡 **Key insight:** OpenTelemetry stable and beta instrumentation packages release as matched sets — upgrade SDK and instrumentation packages together and verify with a smoke request, not independently.

## 🗺️ Baseline Environment

Load credentials from secret management. Environment and release use Langfuse's first-class configuration fields:

```bash
export LANGFUSE_PUBLIC_KEY="pk-lf-..."
export LANGFUSE_SECRET_KEY="sk-lf-..."
export LANGFUSE_BASE_URL="https://cloud.langfuse.com"
export LANGFUSE_TRACING_ENVIRONMENT="dev"
export LANGFUSE_RELEASE="local"
export OPENAI_API_KEY="sk-proj-..."
```

Do not substitute custom `ENVIRONMENT` or `RELEASE` metadata keys. `LANGFUSE_TRACING_ENVIRONMENT` and `LANGFUSE_RELEASE` populate the fields used by Langfuse filters and release analytics. OpenTelemetry resources use the separate `deployment.environment.name` and `service.version` attributes.

## 🏗️ Bootstrap Profile A: Langfuse Direct Tracing and OTLP Metrics

Use this profile for examples 01 and 02. Langfuse owns trace batching and direct export. A separate OpenTelemetry `MeterProvider` sends unsampled operational metrics to a Collector. Do not install a second application `TracerProvider` for the same calls.

> ⚠️ **Watch out:** A second bootstrap can lose provider ownership or duplicate export. Two wrappers creating different span IDs for the same model call double-count generations; two exporters copying one existing span are fan-out.

```python
# observability.py
import os

from langfuse import Langfuse
from opentelemetry import metrics
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource

langfuse = Langfuse(
    release=os.environ["LANGFUSE_RELEASE"],
    environment=os.environ["LANGFUSE_TRACING_ENVIRONMENT"],
    # Keep FastAPI/HTTPX spans needed to connect the two services in example 02.
    should_export_span=lambda span: True,
)

metric_reader = PeriodicExportingMetricReader(
    OTLPMetricExporter(
        endpoint=os.getenv(
            "OTEL_EXPORTER_OTLP_METRICS_ENDPOINT",
            "http://localhost:4318/v1/metrics",
        )
    ),
    export_interval_millis=15_000,
)
meter_provider = MeterProvider(
    resource=Resource.create(
        {
            "service.name": os.environ["OTEL_SERVICE_NAME"],
            "service.version": os.environ["LANGFUSE_RELEASE"],
            "deployment.environment.name": os.environ[
                "LANGFUSE_TRACING_ENVIRONMENT"
            ],
        }
    ),
    metric_readers=[metric_reader],
)
metrics.set_meter_provider(meter_provider)


def shutdown_observability() -> None:
    langfuse.flush()
    meter_provider.shutdown()
    langfuse.shutdown()
```

Initialize this module before instrumenting FastAPI or HTTPX. Call `shutdown_observability()` once from the FastAPI lifespan shutdown path, or in a `finally` block for a script.

## 🔀 Bootstrap Profile B: Centralized Collector Export

Use this profile for example 03. One application-owned OpenTelemetry provider sends traces and metrics to the Collector; the Collector owns Langfuse authentication, redaction, sampling, retry, and fan-out. Do not also initialize a Langfuse direct trace exporter in that process.

> ⚠️ **Watch out:** Adding direct export alongside Collector routing sends the same data twice unless deliberately deduplicated. Choose one export ownership path and one generation creator per physical model call.

```bash
export OTEL_SERVICE_NAME="agent-service"
export OTEL_RESOURCE_ATTRIBUTES="service.version=${LANGFUSE_RELEASE},deployment.environment.name=${LANGFUSE_TRACING_ENVIRONMENT}"
export OTEL_EXPORTER_OTLP_ENDPOINT="http://otel-collector:4318"
export OTEL_EXPORTER_OTLP_PROTOCOL="http/protobuf"
export OTEL_SEMCONV_STABILITY_OPT_IN="http"
```

Configure one `TracerProvider` with an OTLP span exporter and one `MeterProvider` with an OTLP metric exporter, using [../opentelemetry/02_python_instrumentation.md](../opentelemetry/02_python_instrumentation.md). Shut down both providers once when the process exits.

## 🔒 Safe Capture Default

Keep arbitrary question, message, answer and feedback text out of telemetry by default. Regex matching cannot reliably discover every secret in free text. This policy keeps reviewed structured categories and suppresses text entirely:

```python
"""No free-text capture by default. This is a policy boundary, not a secret detector."""
def safe_text(value: str, *, limit: int = 2000) -> str:
    # Arbitrary prose has no reliable regex-only secrecy boundary.
    return '[CONTENT OMITTED]' if value else ''


def safe_record(*, status: str, document_ids: list[str]) -> dict:
    if status not in {'answered', 'no_context', 'failed'}:
        raise ValueError('unknown status')
    allowed = {'doc_001', 'doc_002'}
    return {'status': status, 'document_ids': [x for x in document_ids if x in allowed][:5]}
```

The examples intentionally retain only these fields:

| Source | Retain | Drop or mask |
| --- | --- | --- |
| Question and answer | Content omitted by default; explicitly reviewed storage only | Secrets, email addresses, excess text |
| Retrieved context | Document IDs, ranks, scores, approved short snippets | Full document bodies and ACL metadata |
| Tool calls | Bounded tool name, outcome, approved IDs | Credentials and raw downstream payloads |
| Account data | Tier and region from a small allowlist | Names, email, payment data, free-form fields |
| Feedback | Boolean value; free-text comment omitted | Arbitrary caller metadata |
| Baggage | Opaque user/session IDs and bounded categories | Raw content and authorization decisions |
| Model messages | Content omitted by default | Raw messages by default in restricted workflows |

Apply an export-stage masker as a second line of defense for spans created by integrations. Test the policy with representative secrets, PII, headers, exceptions, prompts, documents, tool results, and feedback.

## ⚠️ Avoid Duplicate Capture

There are four different mechanisms to distinguish:

```text
Langfuse observation helper ---- creates a Langfuse/OTel span
provider/framework integration -- may create a generation span for the same call
global span processor ----------- decides which process spans reach an exporter
Collector fan-out --------------- copies an existing span to destinations
```

Two exporters receiving the same span is intentional fan-out. Two instrumentations wrapping one model call creates two observations and double-counts usage and cost. Pick one generation owner per model call: a Langfuse wrapper, a framework callback, provider OTel instrumentation, or gateway instrumentation. Keep business/root spans from manual instrumentation and configure one global provider ownership model per process.

> 💡 **Key insight:** Two exporters on the same span is intentional fan-out; two instrumentations wrapping the same model call double-counts usage and cost — they look similar but have completely different effects.

## Run the local baselines

Assume basic Python and shell use plus OTel concepts and Python startup/context lessons. From the repository root, install the ranges above into your activated virtual environment, then run:

```bash
python examples/local/verify_local.py
LAB_DISABLE_TIER=1 python examples/local/verify_local.py
```

These commands launch actual Uvicorn servers on loopback ports 8080–8083, send real HTTP requests, validate denied authentication, RAG output and late-feedback replay/conflict, concurrent in-flight ownership, three-service trace identity and baggage enrichment, then clean up their processes. The changed run proves removing enrichment does not break propagation. Expected lines begin `PASS HTTP auth`, `PASS three-service shared trace_id`, and in the changed run `PASS disabling enrichment`.

For manual request/response inspection use [RAG](01_rag_with_otel_and_langfuse.md#first-run-the-complete-local-application), [gateway/agent](02_multi_service_agent.md#run-the-complete-local-services), and [Collector policy tests](03_collector_prometheus_langfuse.md). Files under `local/` are supporting executable assets, not another reading path. Keep ports free and stop manually started servers with Ctrl-C before running the harness.

The local profile uses real Langfuse observation helpers and OTel providers, console spans/metrics, deterministic generation fixtures and local score storage. It verifies payload/parentage/HTTP behavior without proving backend ingestion. To inspect a **live** project, provide real credentials and set `LAB_LANGFUSE_LIVE=1`; the setup then requires all credential fields and applies a suppressive export mask. Live project reads/writes, paid model calls and Kubernetes installation were not run in the local verification. Replace process-local identity/results/feedback with durable, tenant-scoped production adapters before serving real traffic.

## Recap

- One component owns provider startup, and one wrapper owns each generation.
- Console fixtures prove local instrumentation before external service setup.
- Arbitrary text is omitted by default; structured allowlists carry approved categories.
- Authentication and answer ownership precede scores and tool work.
- Separate backend delivery proof from local payload correctness.

## Check yourself

**Two exporters receive one span ID. Are there two generations?**

<details><summary>Answer</summary>

No. That can be intentional fan-out of one completed span. Look for two distinct generation span IDs describing the same physical call before diagnosing duplicate capture.

</details>

**The local runner passes. Does this prove Langfuse Cloud received a score?**

<details><summary>Answer</summary>

No. Local scores use a fixture sink; console output validates spans. Live score ingestion requires a configured backend and verifying the score ID in that project.

</details>

## Try it

Add a new secret canary to feedback in the local runner and leave the export assertion unchanged. Hint: the default policy suppresses the whole comment.

<details><summary>Worked solution</summary>

Submit a comment containing a fake credential. The local request can retain product input for its business role, but the score/export receives `[CONTENT OMITTED]`, so the credential must be absent from all captured telemetry. A regex recognizing only one fake token pattern would not provide this guarantee for arbitrary input.

</details>

## ✅ Example Review Checklist

- Replace placeholder model names with models available in the provider account.
- Keep one primary capture path per model call.
- Return or persist the Langfuse trace ID with user-visible answers when feedback attaches later.
- Derive user, tenant, account, and session identity from authenticated server-side state.
- Flush Langfuse and shut down metric providers in scripts, tests, workers, and serverless functions.
