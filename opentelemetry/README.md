# OpenTelemetry Guide

OpenTelemetry is the vendor-neutral instrumentation layer for modern distributed systems. It gives you a standard way to create traces, metrics, logs, context propagation, and telemetry pipelines without tying application code to a single backend.

This section is a beginner-to-production guide. It starts with the mental model, then moves into Python examples, multi-service propagation, metrics, production collector patterns, deployment, alerting, and the GenAI conventions used by LLM and agent systems.

## 🧭 Reading Path

| File | Purpose |
| --- | --- |
| [../PRODUCTION_TRACING_PLAYBOOK.md](../PRODUCTION_TRACING_PLAYBOOK.md) | Compact production tracing policy, acceptance checklist, and links to the detailed chapters below. |
| [01_concepts.md](01_concepts.md) | The full OTel mental model: signals, context, SDKs, exporters, Collector pipelines, backends, and common pitfalls. |
| [02_python_instrumentation.md](02_python_instrumentation.md) | Practical Python setup for traces, metrics, logs, exporters, and auto-instrumentation. |
| [03_production_architecture.md](03_production_architecture.md) | Collector topologies, deployment patterns, sampling, security, and operations. |
| [deployment/README.md](deployment/README.md) | Image and distribution choices, Docker, Helm vs. Operator, Kubernetes Services, scaling, resilience, security, upgrades, and runbooks. |
| [04_multi_service_examples.md](04_multi_service_examples.md) | Gateway-to-service tracing, W3C Trace Context, baggage, and signal correlation. |
| [05_custom_metrics_alerting.md](05_custom_metrics_alerting.md) | Custom metric design, Prometheus-style export, SLOs, alerts, and runbooks. |
| [06_genai_and_llm_observability.md](06_genai_and_llm_observability.md) | Current GenAI semantic conventions and how they apply to LLM and agent systems. |

**First-time prerequisite:** basic Python and shell use. Read 01 then 02 for the executable trace simulation and local `/chat` service. Stop after 02 for a local baseline; take 04 for remote propagation, 05 for aggregate querying and alerts, 03 plus deployment for production policy. Take 06 when model attempts/streaming need domain instrumentation.

## 📐 When To Use OpenTelemetry Directly

Use raw OpenTelemetry instrumentation when:

- you have multiple services, languages, or telemetry backends;
- you already run an OpenTelemetry Collector;
- you need infrastructure and application metrics alongside LLM traces;
- you want traces to go to Langfuse and metrics/logs to observability backends such as Prometheus, Grafana, Datadog, Honeycomb, or Elastic;
- you need vendor-neutral instrumentation in libraries or shared internal frameworks.

Use the Langfuse SDK when:

- your main goal is LLM observability, prompt/version tracking, and evaluation;
- you are writing Python or JS/TS application code and want higher-level helpers for generations, scores, and attribute propagation;
- you still want OpenTelemetry compatibility but do not want to wire OTLP exporters manually.

A production LLM system may use both APIs, but each process still needs one
trace-provider ownership path. Either let the Langfuse SDK initialize the
provider and add general OpenTelemetry instrumentation to it, or initialize the
provider yourself and attach the Langfuse span processor/exporter. Do not let
two independent bootstraps replace the global provider or export the same span
twice.

```text
Application code
  |-- Langfuse SDK or GenAI instrumentation for LLM traces
  |-- OpenTelemetry SDK/instrumentations for HTTP, DB, queues, metrics, logs
       |
       v
OpenTelemetry Collector
  |-- traces -> Langfuse and/or APM backend
  |-- metrics -> Prometheus-compatible metrics backend
  |-- logs -> log backend
```

## 📌 Official References Used

This guide's compatibility contract was reviewed on August 10, 2026. Core
semantic-convention guidance is anchored to `v1.44.0`; the faster-moving GenAI
material is separately anchored to `open-telemetry/semantic-conventions-genai`
commit `46d43c8949afb53765a202e89f4534eeb75ca3fa` from 2026-08-09. Keep both anchors:
the dedicated GenAI repository can change without a new core release.

References:

- [OpenTelemetry overview](https://opentelemetry.io/docs/what-is-opentelemetry/)
- [OpenTelemetry components](https://opentelemetry.io/docs/concepts/components/)
- [OpenTelemetry traces](https://opentelemetry.io/docs/concepts/signals/traces/)
- [OpenTelemetry metrics](https://opentelemetry.io/docs/concepts/signals/metrics/)
- [OpenTelemetry logs](https://opentelemetry.io/docs/concepts/signals/logs/)
- [OpenTelemetry logs data model](https://opentelemetry.io/docs/specs/otel/logs/data-model/)
- [OpenTelemetry Logs SDK](https://opentelemetry.io/docs/specs/otel/logs/sdk/)
- [OpenTelemetry context propagation](https://opentelemetry.io/docs/concepts/context-propagation/)
- [OpenTelemetry baggage](https://opentelemetry.io/docs/concepts/signals/baggage/)
- [OpenTelemetry resources](https://opentelemetry.io/docs/concepts/resources/)
- [OpenTelemetry instrumentation scope](https://opentelemetry.io/docs/concepts/instrumentation-scope/)
- [OpenTelemetry semantic conventions](https://opentelemetry.io/docs/concepts/semantic-conventions/)
- [OpenTelemetry Python instrumentation](https://opentelemetry.io/docs/languages/python/instrumentation/)
- [OpenTelemetry Python exporters](https://opentelemetry.io/docs/languages/python/exporters/)
- [OpenTelemetry OTLP exporter configuration](https://opentelemetry.io/docs/languages/sdk-configuration/otlp-exporter/)
- [OpenTelemetry Protocol exporter specification](https://opentelemetry.io/docs/specs/otel/protocol/exporter/)
- [OpenTelemetry Python propagation](https://opentelemetry.io/docs/languages/python/propagation/)
- [OpenTelemetry zero-code Python instrumentation](https://opentelemetry.io/docs/zero-code/python/)
- [Prometheus OTLP receiver guide](https://prometheus.io/docs/guides/opentelemetry/)
- [OpenTelemetry Collector configuration](https://opentelemetry.io/docs/collector/configuration/)
- [OpenTelemetry Collector deployment](https://opentelemetry.io/docs/collector/deploy/)
- [OpenTelemetry Collector scaling](https://opentelemetry.io/docs/collector/scaling/)
- [OpenTelemetry Collector internal telemetry](https://opentelemetry.io/docs/collector/internal-telemetry/)
- [OpenTelemetry security configuration best practices](https://opentelemetry.io/docs/security/config-best-practices/)
- [OpenTelemetry sampling](https://opentelemetry.io/docs/concepts/sampling/)
- [Collector tail-sampling processor](https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/main/processor/tailsamplingprocessor)
- [Collector CloudWatch Logs exporter](https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/main/exporter/awscloudwatchlogsexporter)
- [OpenTelemetry GenAI semantic conventions, pinned revision](https://github.com/open-telemetry/semantic-conventions-genai/tree/46d43c8949afb53765a202e89f4534eeb75ca3fa)
- [OpenTelemetry GenAI spans, pinned revision](https://github.com/open-telemetry/semantic-conventions-genai/blob/46d43c8949afb53765a202e89f4534eeb75ca3fa/docs/gen-ai/gen-ai-spans.md)
- [OpenTelemetry GenAI metrics, pinned revision](https://github.com/open-telemetry/semantic-conventions-genai/blob/46d43c8949afb53765a202e89f4534eeb75ca3fa/docs/gen-ai/gen-ai-metrics.md)
- [OpenTelemetry GenAI agent spans, pinned revision](https://github.com/open-telemetry/semantic-conventions-genai/blob/46d43c8949afb53765a202e89f4534eeb75ca3fa/docs/gen-ai/gen-ai-agent-spans.md)
- [Langfuse OpenTelemetry integration](https://langfuse.com/integrations/native/opentelemetry)
