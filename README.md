# OpenTelemetry and Langfuse Guide

Repository compatibility contract reviewed on 2026-08-10. Version-sensitive
examples target OpenTelemetry semantic conventions 1.44.0, the pinned GenAI
convention revision documented below, and Collector Contrib 0.158.0 unless a
chapter states a narrower integration-specific range.

Assumed knowledge: basic Python programming, virtual environments and ordinary command-line use. No tracing, distributed context, PromQL or LLM evaluation background is assumed; those mechanisms are taught in the linked paths. Kubernetes commands additionally require familiarity with pods, Services, namespaces and a disposable cluster.

This repo is a production-focused guide to OpenTelemetry and Langfuse for engineers building modern distributed systems, LLM applications, RAG pipelines, and agentic systems.

It has three goals:

1. Teach OpenTelemetry from fundamentals to production use.
2. Teach Langfuse as a practical LLM observability, evaluation, and metrics platform.
3. Show how OpenTelemetry and Langfuse work together in real Python systems.

## 🧭 Start Here

| Path | Use it when |
| --- | --- |
| [Production tracing playbook](PRODUCTION_TRACING_PLAYBOOK.md) | You want the compact production policy, rollout checklist, and links into the deeper notes. |
| [opentelemetry/README.md](opentelemetry/README.md) | You want to deeply understand OpenTelemetry and production observability architecture. |
| [opentelemetry/deployment/README.md](opentelemetry/deployment/README.md) | You need to deploy, discover, scale, secure, or upgrade OpenTelemetry Collectors. |
| [langfuse/README.md](langfuse/README.md) | You want to instrument, evaluate, and operate LLM applications with Langfuse. |
| [examples/README.md](examples/README.md) | You want concrete Python patterns for RAG, agents, multi-service propagation, metrics, and alerts. |

## 📁 Structure

```text
LangFuseNotes/
|-- PRODUCTION_TRACING_PLAYBOOK.md
|-- opentelemetry/
|   |-- 01_concepts.md
|   |-- 02_python_instrumentation.md
|   |-- 03_production_architecture.md
|   |-- 04_multi_service_examples.md
|   |-- 05_custom_metrics_alerting.md
|   |-- 06_genai_and_llm_observability.md
|   `-- deployment/
|       |-- 01_deployment_decisions.md
|       |-- 02_docker_compose.md
|       |-- 03_kubernetes_installation.md
|       |-- 04_service_discovery_and_clients.md
|       |-- 05_scaling_and_resilience.md
|       `-- 06_security_operations_and_upgrades.md
|
|-- langfuse/
|   |-- 01_overview_data_model.md
|   |-- 02_python_sdk_v4.md
|   |-- 03_otel_ingestion_and_mapping.md
|   |-- 04_production_observability.md
|   |-- 05_evaluation_metrics_alerting.md
|   `-- 06_framework_integrations.md
|
|-- examples/
|   |-- 01_rag_with_otel_and_langfuse.md
|   |-- 02_multi_service_agent.md
|   `-- 03_collector_prometheus_langfuse.md
```

## 📖 Recommended Reading Order

New to both topics:

**First result:** the trace simulation in entry 1 and a real local `/chat` service in entry 2. **Stop point:** after entry 2 you can explain parentage, emit traces/metrics and flush at shutdown; continue when you need shared pipeline policy or LLM-specific evaluation.

1. [OpenTelemetry concepts](opentelemetry/01_concepts.md)
2. [Python instrumentation](opentelemetry/02_python_instrumentation.md)
3. [Production architecture](opentelemetry/03_production_architecture.md)
4. [Langfuse overview and data model](langfuse/01_overview_data_model.md)
5. [Langfuse Python SDK v4](langfuse/02_python_sdk_v4.md)
6. [RAG example](examples/01_rag_with_otel_and_langfuse.md)

Optional continuation: [Framework integrations](langfuse/06_framework_integrations.md) when you already use a provider/framework adapter and satisfy that note's explicit prerequisites. The manual RAG baseline does not require a framework.

Already an OpenTelemetry engineer:

**Outcome:** choose capture/routing/sampling ownership and an observed rollout gate. **Stop point:** after the policy and architecture decisions when an existing deployment already satisfies their checks.

1. [Production tracing playbook](PRODUCTION_TRACING_PLAYBOOK.md)
2. [Production architecture](opentelemetry/03_production_architecture.md)
3. [GenAI and LLM observability](opentelemetry/06_genai_and_llm_observability.md)
4. [Langfuse OTLP ingestion and mapping](langfuse/03_otel_ingestion_and_mapping.md)
5. [Collector, Prometheus, Langfuse, and alerts](examples/03_collector_prometheus_langfuse.md)

Building production LLM or agent systems:

**Prerequisites:** Langfuse 01–02 and OTel 01–02, or equivalent tested knowledge. New readers should take the first-time path above. **Outcome:** diagnose an index regression, reject a harmful candidate despite a higher mean, and verify authenticated multi-service instrumentation. **Stop point:** after the worked incident and release gate; continue to integration when work crosses services.

1. [Langfuse production observability](langfuse/04_production_observability.md)
2. [Evaluation, metrics, and alerting](langfuse/05_evaluation_metrics_alerting.md)
3. [Framework integrations](langfuse/06_framework_integrations.md)
4. [Multi-service OpenTelemetry examples](opentelemetry/04_multi_service_examples.md)
5. [Multi-service agent example](examples/02_multi_service_agent.md)

Deploying OpenTelemetry Collectors:

**Prerequisites:** OTel 01–02; Kubernetes-specific steps assume pods/Services/namespaces and a disposable cluster. **First result:** local accepted/sent/backend canary by entry 2. **Stop point:** a loopback validated pipeline; continue to TLS/auth, finite buffers and upgrade gates before production.

1. [Deployment decisions](opentelemetry/deployment/01_deployment_decisions.md)
2. [Docker Compose baseline](opentelemetry/deployment/02_docker_compose.md)
3. [Kubernetes installation](opentelemetry/deployment/03_kubernetes_installation.md)
4. [Service discovery and client configuration](opentelemetry/deployment/04_service_discovery_and_clients.md)
5. [Scaling and resilience](opentelemetry/deployment/05_scaling_and_resilience.md)
6. [Security, operations, and upgrades](opentelemetry/deployment/06_security_operations_and_upgrades.md)

> 💡 Scan **Current Guidance Highlights** before starting any path — it flags API changes and naming conventions that affect every section.

## ✅ Current Guidance Highlights

- Langfuse Python SDK examples use SDK v4 APIs from `langfuse`: `get_client`, `observe`, and `propagate_attributes`.
- Use `LANGFUSE_BASE_URL`, not legacy `LANGFUSE_HOST`, in new code.
- Langfuse OTLP ingestion uses OTLP/HTTP and Basic Auth; OTLP/gRPC is not supported by Langfuse ingestion.
- Use current GenAI semantic convention names such as `gen_ai.provider.name`, `gen_ai.operation.name`, and `gen_ai.usage.*`.
- Prefer named correlated logs for new events and exceptions. OTel has announced gradual deprecation of span-event recording APIs; existing APIs/data remain supported during the transition. See [events and migration](opentelemetry/01_concepts.md#why-new-events-belong-in-the-logs-pipeline).
- Send operational metrics to a metrics backend for alerts. Use Langfuse for LLM traces, generations, scores, datasets, quality analytics, cost, and workflow investigation.
- Filter Langfuse independently from APM: preserve the root and every ancestor of retained GenAI spans, and omit operational-only subtrees. See [Collector and direct-export options](langfuse/03_otel_ingestion_and_mapping.md#keep-a-rooted-genai-view-instead-of-operational-subtrees).
- Treat baggage as an allowlisted propagation mechanism, not as a place for secrets or arbitrary user data.
- Pin the Collector image and chart independently, validate the exact distribution's component set, and use trace-ID-aware routing before scaling a tail-sampling tier.

## 🔗 Official References

- OpenTelemetry docs: <https://opentelemetry.io/docs/>
- OpenTelemetry Python docs: <https://opentelemetry.io/docs/languages/python/>
- OpenTelemetry span-event deprecation: <https://opentelemetry.io/blog/2026/deprecating-span-events/>
- OpenTelemetry event semantic conventions: <https://opentelemetry.io/docs/specs/semconv/general/events/>
- OpenTelemetry Collector docs: <https://opentelemetry.io/docs/collector/>
- OpenTelemetry GenAI semantic conventions: <https://github.com/open-telemetry/semantic-conventions-genai>
- Langfuse docs: <https://langfuse.com/docs>
- Langfuse SDK overview: <https://langfuse.com/docs/observability/sdk/overview>
- Langfuse OpenTelemetry ingestion: <https://langfuse.com/integrations/native/opentelemetry>
- Langfuse integrations: <https://langfuse.com/integrations>
- Langfuse Python reference: <https://python.reference.langfuse.com/langfuse>

## Pinned teaching baseline and current compatibility

Checked 2026-10-14. Historical examples retain their explicit pins; “current” does not mean silently changing an SDK major or chart. Lock resolved Python packages together and repeat the local/external gates on upgrades.

| Component | Teaching baseline | Current migration boundary |
|---|---|---|
| Langfuse Python | >=4.14,<5; mixed local examples verified with 4.18.0; LF SDK smoke pins 4.17.0 | Python v5 requires Python >=3.11 and Langfuse v4 >=4.59.0/Cloud; follow the [v5 migration](https://langfuse.com/docs/observability/sdk/upgrade-path/python-v4-to-v5). |
| Langfuse server | Existing SDK v4 course; historical preview language is scoped | Server v4 GA; Cloud legacy API/ingest removals planned 2026-11-16. Audit actual API method mappings via [compatibility](https://langfuse.com/docs/compatibility). |
| Collector Contrib | 0.158.0 root pipeline; deployment guide 0.157.0 | Validate each exact distribution; newer components are migration candidates, not available on old pins. |
| Helm Collector chart | Deployment 0.168.0 paired with k8s image 0.157.0 | Pin chart and image independently; render actual merged configuration before installation. |
| OTel conventions | Core 1.44.0 plus GenAI commit 46d43c89 | GenAI remains evolving; new inference metric names require a producer/dashboard migration together. |

## What's changing

Checked 2026-10-14 against primary sources. These are status and migration context for the pinned lessons.

| Item | Status | What to do | Source |
|---|---|---|---|
| Python SDK v5 / JS SDK v6 | GA | Check server and removed methods before moving majors; see Langfuse 02. | [Release](https://langfuse.com/changelog/2026-10-14-python-sdk-v5-js-sdk-v6) |
| Langfuse server v4 and Cloud cutoff | GA / DEPRECATED | Migrate legacy API consumers by 2026-11-16; retain tested SDK v4 where compatible. | [Compatibility](https://langfuse.com/docs/compatibility) |
| Kubernetes attributes processor v1 | GA | Diff attribute enrichment during Collector upgrades; deployment 03/06. | [Migration](https://opentelemetry.io/blog/2026/k8s-attributes-processor-v1/) |
| Evaluator APIs, backfills and multimodal inputs | GA | Version evaluator definitions and targeting; recalibrate new inputs, Langfuse 05. | [Evaluator API](https://langfuse.com/changelog/2026-08-27-stable-evaluator-api), [backfills](https://langfuse.com/changelog/2026-09-07-evaluator-backfills), [multimodal](https://langfuse.com/changelog/2026-09-01-multi-message-prompts-and-multimodal-inputs) |
| Boolean score aggregate view | GA | Match view to score type and server API, Langfuse 05. | [Metrics API](https://langfuse.com/docs/metrics/features/metrics-api) |
| Cardinality overflow series | GA, SDK support varies | Monitor overflow and bounded dimensions; filtered SLO ratios can lose cohort labels, OTel 05. | [Cardinality guide](https://opentelemetry.io/blog/2026/cardinality-limits-in-opentelemetry/) |
| Declarative configuration schema 1.0 | GA schema, language maturity varies | Check implementation support before replacing the Python bootstrap. | [Stable schema](https://opentelemetry.io/blog/2026/stable-declarative-config/) |
| Collector 0.163 adaptive sampling and rotation | PREVIEW for alpha samplers; component-specific rotation | Test newer component schemas and rollout separately from .157/.158 pins. | [Release](https://github.com/open-telemetry/opentelemetry-collector-contrib/releases/tag/v0.163.0) |
| Profiles | PREVIEW, public alpha | Optional performance investigation beyond the core Python labs. | [Announcement](https://opentelemetry.io/blog/2026/profiles-alpha/) |
| Environment-variable carrier | PREVIEW, release candidate | Consider CLI/subprocess tracing after checking language support and trust boundary. | [Proposal](https://opentelemetry.io/blog/2026/environment-variable-context-propagation/) |
| OBI stdout/stderr trace correlation | GA, opt-in | Linux alternative with kernel/privilege/logging constraints; manual product spans still needed. | [Maintainer guidance](https://opentelemetry.io/blog/2026/obi-trace-log-correlation/) |
| OTel-Arrow Dataflow Engine | PREVIEW | Controlled high-volume efficiency experiments; outside this baseline. | [Incubation](https://opentelemetry.io/blog/2026/otel-arrow-phase-2/) |
| Span-event APIs | Announced gradual deprecation; SDK adoption varies | Prefer named correlated logs for new instrumentation; existing OTLP span events remain readable. | [Deprecation plan](https://opentelemetry.io/blog/2026/deprecating-span-events/) |
| GenAI inference metric schema | PREVIEW conventions | Separate inference from non-inference operation duration and migrate queries with the producer, OTel 06. | [GenAI metrics](https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-metrics/) |

[Glossary](GLOSSARY.md) links lookup terms to their teaching owners. [Architecture references](architecture/README.md) provide compact tracing and metric design lookup after the tutorials.
