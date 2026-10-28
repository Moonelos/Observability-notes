# Langfuse Guide

Teaching baseline: Python SDK 4.17.0; server-v4 observation-first model. Migration research checked 2026-10-28.

Langfuse is an observability, evaluation, prompt management, and metrics platform for LLM applications. It is built on OpenTelemetry, but it adds LLM-specific concepts that general observability backends do not usually understand well: prompts, generations, model usage, cost, user feedback, scores, datasets, experiments, and review workflows.

This section assumes you already understand the OpenTelemetry basics in [../opentelemetry/README.md](../opentelemetry/README.md). Start here when you want to use Langfuse in production Python applications.

Audience: basic Python programming and ordinary shell use, with the OTel trace/context/export
foundation taught in this repository. Outcomes: explain an SSO request's evidence, run a local real-SDK
trace, diagnose a source-selection regression, compare pinned evaluations, and design monitored
rollout/recovery. Full Langfuse server installation, framework programming, statistically powered
benchmark design and multimodal application development are outside this path. Hosted ingestion,
experiments and notifications need project credentials; local success does not verify those gates.

## 🧭 Mental Model

Langfuse is the LLM behavior ledger for an application. It records what the user or system asked for, which workflow ran, which model calls, retrievals, tools, agents, and guardrails happened, what they cost, whether they were good, and which release or prompt version produced them.

Langfuse solves:

- LLM trace inspection: "Why did this answer happen?"
- Quality measurement: "Are answers getting better or worse?"
- Prompt and model iteration: "Which version won?"
- Feedback loops: "Which production failures should become regression tests?"
- LLM-specific analytics: "What did this workflow cost by model, release, user segment, and score?"
- Native monitors: "Did observation cost, latency, volume, or a quality score cross a sustained threshold?"

Langfuse does not replace:

- Infrastructure metrics and SLO alerting for CPU, memory, queues, network, service errors, and other unsupported signals.
- Incident-management escalation, ownership, deduplication, and on-call workflows beyond monitor automations.
- General log storage.
- Authorization, data-loss prevention, or privacy policy enforcement.
- A model gateway, prompt runtime, vector database, or eval framework by itself.

The practical shape is:

```text
product request
  -> application / framework instrumentation
  -> Langfuse trace with observations
  -> scores, feedback, datasets, experiments, metrics
  -> engineers debug, reviewers annotate, dashboards compare versions
```

When something goes wrong, start with metrics or user feedback, open the relevant Langfuse traces, classify the failure, turn representative examples into dataset items, run experiments, and ship the fix with release/version markers.

## 🗺️ Reading Path

| File | What it covers |
| --- | --- |
| [01_overview_data_model.md](01_overview_data_model.md) | Langfuse's trace, observation, generation, score, dataset, prompt, and metric concepts |
| [02_python_sdk_v4.md](02_python_sdk_v4.md) | Pinned SDK v4: complete local smoke, context, export and hardening |
| [03_otel_ingestion_and_mapping.md](03_otel_ingestion_and_mapping.md) | Sending raw OpenTelemetry spans to Langfuse and mapping attributes correctly |
| [04_production_observability.md](04_production_observability.md) | Production workflows, privacy, sampling, environments, releases, sessions, and operations |
| [05_evaluation_metrics_alerting.md](05_evaluation_metrics_alerting.md) | Scores, online/offline evaluation, Langfuse metrics, and alerting patterns |
| [06_framework_integrations.md](06_framework_integrations.md) | Current integration patterns for LangChain, OpenAI, LiteLLM, and OpenTelemetry-native libraries |

First learn 01 and run 02; you can stop there to inspect and emit a complete local trace. Continue through 04 and 05 to operate releases and evaluation gates. Chapter 03 is conditional for raw OTLP/Collector ownership; 06 is conditional for an existing framework/provider integration. Read the guide in order if you are designing a new rollout. Jump to the integration or production file when you are upgrading an existing service.

## 📐 Which Integration Should You Use?

| Situation | Recommended path |
| --- | --- |
| Python or JavaScript/TypeScript app and you can add Langfuse code | Use the Langfuse SDK. For Python, use SDK v4 APIs from `langfuse`: `get_client`, `observe`, and `propagate_attributes`. |
| Existing service already emits OpenTelemetry spans | Send OTLP/HTTP traces to Langfuse, either directly or through the Collector. |
| Polyglot microservices | Use OpenTelemetry everywhere; use Langfuse SDKs in Python/JS LLM services where they add value; route GenAI traces to Langfuse. |
| You need SLO alerts on request rate, errors, queue depth, or saturation | Export OpenTelemetry metrics to a metrics backend; these infrastructure signals and escalation workflows remain outside Langfuse. |
| You need observation or score thresholds for cost, latency, volume, or quality | Create a native Langfuse Monitor with filters, warning/alert thresholds, a window, no-data and renotification behavior, then link Slack, webhook, or GitHub Actions automations. |
| You need quality, cost, latency, token, prompt-version, or user feedback analytics | Use Langfuse traces, scores, dashboards, native Monitors, and Metrics API v2. |

Decision points:

- Use SDK instrumentation when you own the LLM application code and need rich trace shape.
- Use framework integrations when LangChain, LangGraph, OpenAI SDK, LiteLLM, or another integration already sees the calls you care about.
- Use raw OTLP when you need language/runtime neutrality or central Collector routing.
- Use both SDK and OpenTelemetry carefully in the same process only when you understand which spans each exporter sends. Duplicate model spans make costs and debugging noisy.

> ⚠️ **Watch out:** Running both the Langfuse SDK exporter and a separate OTLP exporter in the same process for the same model calls silently doubles your token count and cost figures in dashboards.

## 🏷️ Shared Terminology

Use these terms consistently across the guide:

| Term | Meaning |
| --- | --- |
| Trace | One end-to-end product workflow, usually one request, message, job, or agent run. |
| Observation | One timed step inside a trace. In OpenTelemetry terms, this is a span represented in Langfuse. |
| Generation | A model-call observation with model, input, output, parameters, token usage, and optional cost fields. |
| Retriever | An observation for search or context lookup, usually recording query, top-k, document IDs, scores, and index metadata. |
| Tool | An agent or workflow operation against an external capability such as search, account lookup, code execution, or an internal API. |
| Score | A quality or feedback object attached to a trace, observation, session, or dataset run. |
| Dataset | A curated collection of inputs, expected outputs, and metadata used for experiments and regression tests. |
| Experiment | A run of application logic against dataset items, usually with evaluators that produce scores. |
| Release | The deployed software artifact: Git SHA, image tag, or build number. |
| Version | The logical workflow, prompt, chain, agent, or evaluator version. |
| Environment | Deployment context such as `dev`, `staging`, or `prod`. |

## 🧭 Production Mental Model

Use Langfuse as the LLM observability and evaluation system, not as a replacement for your whole telemetry stack.

```text
Application
  |
  |-- Langfuse SDK or OTLP spans --> Langfuse
  |       traces, generations, prompts, scores, sessions, cost, quality
  |       native monitors -> Slack / webhook / GitHub Actions
  |
  |-- OpenTelemetry metrics -------> Prometheus / managed metrics backend
  |       latency SLOs, errors, saturation, alerting
  |
  |-- OpenTelemetry or app logs ----> log backend
          incident forensics, audit trails, debugging
```

The production setup uses each signal deliberately. Langfuse explains LLM and agent behavior and can notify on supported observation/score thresholds. The external metrics and incident stack owns infrastructure SLOs, unsupported signals, paging policy, and advanced escalation. Logs provide exact operational evidence.

> 💡 **Key insight:** Langfuse answers "what happened in the LLM workflow and was it good?" — it is not a general-purpose alerting, logging, or infrastructure monitoring system, and trying to make it one creates blind spots.

## 🔄 End-to-End Lifecycle

1. A user request, scheduled job, or agent task enters your system.
2. The application creates a root trace/observation with stable workflow name, release, environment, user/session IDs, tags, and safe metadata.
3. Retrieval, tool, guardrail, agent, chain, and generation observations are created as the workflow runs.
4. The SDK or OTLP exporter batches telemetry and sends it to Langfuse. Operational metrics and logs go to their own backends.
5. Langfuse maps OpenTelemetry spans into observations, derives trace-level fields, and computes LLM-specific views for latency, cost, usage, and quality.
6. Users, humans, code evaluators, and LLM judges attach scores.
7. Engineers inspect traces, compare release/version dimensions, build datasets from failures, and run experiments before the next rollout.
8. Native Monitors evaluate supported cost, latency, volume, and score thresholds; external alerting evaluates infrastructure SLOs and drives the broader incident workflow.

The main design goal is not "capture everything." It is "capture enough safe context that a future engineer can explain a bad answer, reproduce it, and know whether the fix helped."

## 🗺️ Production Architecture Shapes

| Shape | Use when | Responsibilities |
| --- | --- | --- |
| Single Python LLM service with Langfuse SDK | You own the service and need rich traces quickly | SDK records observations, generations, scores, and prompt links; OTel metrics go to metrics backend. |
| Gateway plus agent/RAG services | Multiple internal services contribute to one user-visible answer | Gateway sets request identity and W3C trace context; downstream services record LLM-specific observations; baggage carries only allowlisted trace attributes. |
| Central OpenTelemetry Collector | Platform team controls routing, filtering, redaction, and backend policy | Apps export OTLP to Collector; Collector routes complete LLM traces to Langfuse and operational telemetry elsewhere. |
| Model gateway with LiteLLM or similar | Many apps call models through one provider abstraction | Gateway captures provider calls and cost; applications should still pass user/session/workflow attributes and add business spans where needed. |
| Offline evaluation worker | You run datasets, evaluators, or batch scoring outside request path | Worker runs experiments, records traces and scores, flushes before exit, and writes release-gate results to CI/CD or dashboards. |

## ✅ Production Readiness Themes

- Configuration: set credentials, base URL, environment, release, sample rate, and debug flags from environment/secret management.
- Security: keep Langfuse keys out of code, rotate them like other service credentials, and keep Collector receivers private.
- Privacy: redact or suppress inputs/outputs before export; never put secrets, raw PII, or large sensitive documents in metadata, tags, or baggage.
- Scaling: batch exports, use sampling only after deciding which failures and high-risk segments must always be retained, and keep metric labels low-cardinality.
- Reliability: flush in short-lived processes, test authentication at startup when appropriate, and validate Collector configs before deployment.
- Environment separation: use separate projects or strict environment fields when prod/dev access, retention, or compliance policies differ.
- Testing: include tracing smoke tests, dataset experiments for prompt/model changes, and dashboard/alert validation in staging.

## 🔌 Official References

- Langfuse SDK overview: <https://langfuse.com/docs/observability/sdk/overview>
- Langfuse instrumentation: <https://langfuse.com/docs/observability/sdk/instrumentation>
- Langfuse advanced SDK features: <https://langfuse.com/docs/observability/sdk/advanced-features>
- Langfuse concepts/data model: <https://langfuse.com/docs/observability/data-model>
- Langfuse observation types: <https://langfuse.com/docs/observability/features/observation-types>
- Langfuse OpenTelemetry ingestion: <https://langfuse.com/integrations/native/opentelemetry>
- Langfuse metrics: <https://langfuse.com/docs/metrics/overview>
- Langfuse monitors: <https://langfuse.com/docs/metrics/features/monitors>
- Langfuse scores: <https://langfuse.com/docs/evaluation/scores/overview>
- Langfuse datasets: <https://langfuse.com/docs/evaluation/experiments/datasets>
- Langfuse experiments via SDK: <https://langfuse.com/docs/evaluation/experiments/experiments-via-sdk>
- Python SDK reference: <https://python.reference.langfuse.com/langfuse>
- Langfuse integrations: <https://langfuse.com/integrations>

## ✅ Guide Checklist

- Pick one primary ingestion path per service: SDK, framework integration, raw OTLP, or gateway.
- Name traces by product workflow, not request-specific values.
- Add user/session, release, version, environment, tags, and safe metadata consistently.
- Record model, input/output policy, token usage, retrieval IDs/scores, tool errors, and guardrail outcomes.
- Send operational metrics and logs to purpose-built backends.
- Attach scores for feedback, evaluators, safety checks, and release gates.
- Convert important production failures into dataset items.
- Verify examples against the official docs before copying them into production.

## What's changing

Checked 2026-10-28. SDK major numbers and server major numbers are independent. This course keeps
its executable **Python SDK 4.17.0** baseline so its examples remain reproducible; new deployments
should assess the GA upgrade after testing the server/API compatibility boundary.

| Status | Change | Action for this path |
| --- | --- | --- |
| GA | Server v4 and Python SDK v5; v5 needs Python ≥3.11 and Cloud or self-hosted server ≥4.59.0 | Retain the v4 pin during reproduction; upgrade the server before moving a self-hosted client to v5. |
| DEPRECATED | Cloud legacy read APIs/trace ingestion and built-in trace-level evaluators sunset 2026-11-16 | Inventory `api.legacy.*`, old endpoints, rules and exports; migrate reads to observations v2, metrics v2, scores v3 and experiment APIs. SDK-v4 OTLP tracing and score-create writes remain supported. |
| GA | Stable evaluator/rule APIs with version history | Treat evaluator updates as rollout changes; 05 explains calibration and version evidence. |
| GA | Historical evaluator backfill | Budget judge cost and distinguish old observation time from new evaluation time; it cannot restore dropped traces. |
| GA | Dedicated `scores-boolean` view and native boolean-score alerts | Use true-rate aggregation for pass/fail scores; validate server availability and no-data behavior. |
| GA | Multi-message evaluator prompts and multimodal evaluation | Optional extension: requires compatible judge/provider media support and reviewed delivery/size/privacy policy. |
| GA | Project API-key permissions | Provision Ingestion, Scores ingestion or Viewer keys for their specific jobs; test allowed and denied operations in [04](04_production_observability.md#rotate-keys-without-losing-the-delivery-proof). Existing keys retain their permissions. |
| GA | SDK v5.0.3/5.0.4 lifecycle fixes and caller-owned experiment identity | Add final-score receipt and actual worker shutdown to the [02 upgrade gates](02_python_sdk_v4.md#qualify-a-v5-lifecycle-upgrade); preserve a deliberate experiment ID across resumed workers in [05](05_evaluation_metrics_alerting.md#keep-experiment-identity-separate-from-display-names). |
| GA | Experiment charts, baseline statistics and item score thresholds | Inspect critical cases as well as summary improvements; [05](05_evaluation_metrics_alerting.md#inspect-the-same-gate-in-a-hosted-experiment) connects the UI to the existing local gate. |
| GA | Opt-in score metadata/provenance blob exports | Enable fields deliberately and validate the next file; earlier exports are unchanged. See [05](05_evaluation_metrics_alerting.md#preserve-score-lineage-in-warehouse-exports). |

Sources: [compatibility matrix](https://langfuse.com/docs/compatibility),
[v4-to-v5 migration](https://langfuse.com/docs/observability/sdk/upgrade-path/python-v4-to-v5),
[stable evaluator API](https://langfuse.com/changelog/2026-08-27-stable-evaluator-api),
[backfills](https://langfuse.com/changelog/2026-09-07-evaluator-backfills),
[metrics views](https://langfuse.com/docs/metrics/features/metrics-api),
[alerts](https://langfuse.com/docs/observability/features/alerts), and
[multi-message/media evaluation](https://langfuse.com/changelog/2026-09-01-multi-message-prompts-and-multimodal-inputs).
Additional migration context: [SDK v5 release](https://langfuse.com/changelog/2026-10-14-python-sdk-v5-js-sdk-v6)
adds typed/nested metadata filters, gzip span export, experiment URLs and batched direct score writes.
Use its migration mapping before assuming a one-score `api.scores.create` call has the same shape.
[API-key expiration](https://langfuse.com/changelog/2026-10-07-api-key-expirations) is GA: rotate the
replacement into exporters before the old key expires, and prove delivery with a canary. The
[redesigned session view](https://langfuse.com/changelog/2026-10-13-redesigned-session-view) is GA;
it improves inspection across turns without changing which trace a late vote targets.

Typed decision-model evaluators are GA integrations for
[OpenAI decision models](https://langfuse.com/changelog/2026-10-07-openai-decision-model-evaluators)
and [Jev](https://langfuse.com/changelog/2026-09-22-jev-as-a-judge). Treat them as optional judge
backends under the same human-calibration/critical-case gate in 05; a specialized score format
does not establish your rubric's validity. [CLI 1.0](https://langfuse.com/changelog/2026-08-21-langfuse-cli-v1)
is GA for terminal/automation access, conditional on approved API credentials and access controls.

**PREVIEW / roadmap, not a released guarantee:** the
[current roadmap](https://langfuse.com/docs/roadmap) lists a Langfuse Gateway, multi-span/session/
trajectory evaluation, transcript and proactive-issue-detection work.
These directional items do not replace this course's tested ingestion or evaluation path.
[Organization feature previews](https://langfuse.com/changelog/2026-08-25-organization-feature-previews)
provide opt-in controls; turning a preview on does not make its API stable. API-key permissions moved to GA on October 16; they are no longer a roadmap dependency.

The researched GA changes supersede the old preview framing; experimental integrations still
require their own locked-version contract. No preview feature is necessary for this path.

For a controlled upgrade, inventory imports and direct API calls, remove deprecated calls using the
migration mapping, and reproduce the local tree, typed scores, pinned experiment and staging alert
with an exact new lockfile. Compare parent IDs, usage, score targets and query outputs. Promote
only after delivery and evaluation gates pass; retain the tested compatible server/config/client
bundle for rollback. A client downgrade cannot undo a server storage migration, so test the
server's documented downgrade boundary separately.


The October additions above are documented in the [key-permissions release](https://langfuse.com/changelog/2026-10-16-project-api-key-permissions),
[SDK 5.0.3](https://github.com/langfuse/langfuse-python/releases/tag/v5.0.3),
[SDK 5.0.4](https://github.com/langfuse/langfuse-python/releases/tag/v5.0.4),
[experiment comparison release](https://langfuse.com/changelog/2026-10-19-experiments) and
[score-export release](https://langfuse.com/changelog/2026-10-22-blob-storage-score-field-groups),
checked 2026-10-28. These are migration continuations; the local v4 lab retains its exact pin.

**GA, conditional self-hosting upgrade:** from server 4.71.0, the web/worker images use hardened
UBI 9 bases without `curl`, Python or a package manager. Review custom images and health probes;
use the supported probe/build approach before rollout. Government-edition FIPS mode also requires
the licensed deployment, host and validated-module conditions; enabling a variable alone does not
make Langfuse a FIPS-validated product. Full server installation remains outside this course.
[Hardened-image and FIPS release](https://langfuse.com/changelog/2026-10-23-fips-mode), checked 2026-10-28.
