# Glossary

Lookup aid. Follow each link for the causal explanation and worked example.

| Term | Meaning and teaching owner |
|---|---|
| Observability | Inferring system behavior from emitted evidence; [OTel concepts](opentelemetry/01_concepts.md). |
| Telemetry | Measurements and records describing a system; [concepts](opentelemetry/01_concepts.md). |
| Trace | One execution represented by related spans sharing a trace ID; [concepts](opentelemetry/01_concepts.md). |
| Span | One timed operation with identity, parent, attributes and status; [concepts](opentelemetry/01_concepts.md). |
| Span kind | The operation's server/client/internal/producer/consumer role; [concepts](opentelemetry/01_concepts.md). |
| Trace ID / span ID | Group identity versus individual operation identity; [concepts](opentelemetry/01_concepts.md). |
| Parent | The span context under which a new span starts; [concepts](opentelemetry/01_concepts.md). |
| Link | A relationship that does not establish parentage; [concepts](opentelemetry/01_concepts.md). |
| Context | Execution-local carrier of the active span and other scoped values; [concepts](opentelemetry/01_concepts.md). |
| Propagation | Serializing and reconstructing context across a transport boundary; [multi-service](opentelemetry/04_multi_service_examples.md). |
| Carrier | Transport fields containing serialized context; [concepts](opentelemetry/01_concepts.md). |
| traceparent | W3C header carrying trace/span identity and flags; [concepts](opentelemetry/01_concepts.md). |
| tracestate | Vendor-specific trace context accompanying traceparent; [concepts](opentelemetry/01_concepts.md). |
| Baggage | Propagated request facts, distinct from exported span attributes; [multi-service](opentelemetry/04_multi_service_examples.md). |
| Attribute | A key/value describing a record or measurement; [concepts](opentelemetry/01_concepts.md). |
| Resource | Identity of the telemetry-producing runtime; [Python](opentelemetry/02_python_instrumentation.md). |
| Instrumentation scope | Identity of the code that emitted telemetry; [concepts](opentelemetry/01_concepts.md). |
| Semantic conventions | Standard meanings and names for telemetry fields; [concepts](opentelemetry/01_concepts.md). |
| API / SDK | Recording interface versus its configured runtime implementation; [Python](opentelemetry/02_python_instrumentation.md). |
| Provider | Runtime owner creating tracers/meters/loggers; [Python](opentelemetry/02_python_instrumentation.md). |
| Auto-instrumentation | Library hooks recording protocol work and propagation; [Python](opentelemetry/02_python_instrumentation.md). |
| Manual instrumentation | Explicit recording of application-specific operations; [Python](opentelemetry/02_python_instrumentation.md). |
| Lifespan | Application startup/shutdown scope owning long-lived clients; [Python](opentelemetry/02_python_instrumentation.md). |
| Exporter | Sender of completed telemetry to a destination; [Python](opentelemetry/02_python_instrumentation.md). |
| Processor | A signal-specific processing stage before export; [production architecture](opentelemetry/03_production_architecture.md). |
| OTLP | OpenTelemetry's telemetry transport protocol; [Python endpoint rules](opentelemetry/02_python_instrumentation.md). |
| Collector | Receiver/processing/export infrastructure between emitters and backends; [architecture](opentelemetry/03_production_architecture.md). |
| Receiver | Collector input component; [architecture](opentelemetry/03_production_architecture.md). |
| Connector | Component connecting Collector pipelines; [concepts](opentelemetry/01_concepts.md). |
| Extension | Collector service capability outside the signal data path; [concepts](opentelemetry/01_concepts.md). |
| Fan-out | Copying one record to multiple destinations; [architecture](opentelemetry/03_production_architecture.md). |
| Head sampling | Trace recording decision made near trace start; [architecture](opentelemetry/03_production_architecture.md). |
| Tail sampling | Stateful decision after buffering trace spans; [architecture](opentelemetry/03_production_architecture.md). |
| Trace affinity | Routing spans with the same trace ID to the same sampler; [scaling](opentelemetry/deployment/05_scaling_and_resilience.md). |
| Metric | Aggregated numeric observations with a defined stream contract; [concepts](opentelemetry/01_concepts.md). |
| Instrument | API object accepting metric measurements; [metrics](opentelemetry/05_custom_metrics_alerting.md). |
| Counter | Monotonic accumulated quantity between resets; [metrics](opentelemetry/05_custom_metrics_alerting.md). |
| UpDownCounter | Instrument recording positive and negative changes; [metrics](opentelemetry/05_custom_metrics_alerting.md). |
| Gauge | Current measured value rather than an accumulating total; [metrics](opentelemetry/05_custom_metrics_alerting.md). |
| Histogram | Distribution summarized by counts, sum and bucket boundaries; [metrics](opentelemetry/05_custom_metrics_alerting.md). |
| Temporality | Whether a point describes an interval delta or cumulative history; [concepts](opentelemetry/01_concepts.md). |
| Exemplar | A representative measurement carrying trace correlation without a trace-ID dimension; [concepts](opentelemetry/01_concepts.md). |
| Cardinality | Number of distinct attribute combinations/time series; [metrics](opentelemetry/05_custom_metrics_alerting.md). |
| Overflow series | Aggregation of excess combinations after cardinality limits, losing original dimensions; [metrics](opentelemetry/05_custom_metrics_alerting.md). |
| PromQL | Prometheus query language over time series and labels; [metrics bridge](opentelemetry/05_custom_metrics_alerting.md). |
| Rate | Reset-aware change per second over a selected time window; [metrics](opentelemetry/05_custom_metrics_alerting.md). |
| Quantile | Estimated value below which a fraction of observations falls; [metrics](opentelemetry/05_custom_metrics_alerting.md). |
| SLI / SLO | Measured service indicator versus target over a defined window; [metrics](opentelemetry/05_custom_metrics_alerting.md). |
| Error budget / burn | Allowed bad fraction versus its consumption relative to target; [metrics](opentelemetry/05_custom_metrics_alerting.md). |
| Pending / firing | Alert condition present but waiting for persistence versus active after it; [metrics](opentelemetry/05_custom_metrics_alerting.md). |
| Named event | Timestamped log with a stable event_name and optional trace correlation; [Python](opentelemetry/02_python_instrumentation.md). |
| Canary | Known telemetry record verifying a specific delivery/policy gate; [deployment baseline](opentelemetry/deployment/02_docker_compose.md). |
| Persistent queue | Exporter requests stored for recovery across compatible restarts; [Compose](opentelemetry/deployment/02_docker_compose.md). |
| Net drain rate | Recovery export throughput minus ongoing arrivals; [scaling](opentelemetry/deployment/05_scaling_and_resilience.md). |
| TLS / mTLS | Server-verified encrypted transport / mutual certificate verification; [security](opentelemetry/deployment/06_security_operations_and_upgrades.md). |
| Pod / namespace | Kubernetes workload runtime / named isolation and naming scope; [installation](opentelemetry/deployment/03_kubernetes_installation.md). |
| Deployment / DaemonSet | Managed replicated pods / node-associated pods; [installation](opentelemetry/deployment/03_kubernetes_installation.md). |
| Service / EndpointSlice | Stable service address / discovered backend endpoint membership; [discovery](opentelemetry/deployment/04_service_discovery_and_clients.md). |
| RBAC | Role-based authorization for Kubernetes API access; [installation](opentelemetry/deployment/03_kubernetes_installation.md). |
| Helm chart | Versioned template/package rendered into Kubernetes objects; [installation](opentelemetry/deployment/03_kubernetes_installation.md). |
| Observation | Langfuse representation of a timed workflow step; [data model](langfuse/01_overview_data_model.md). |
| Generation | Observation describing one model interaction and available usage; [data model](langfuse/01_overview_data_model.md). |
| Session | Correlation of related product interactions beyond one trace; [data model](langfuse/01_overview_data_model.md). |
| Managed prompt | Versioned prompt artifact referenced by an application; [data model](langfuse/01_overview_data_model.md). |
| Score | Judgment attached to a trace/observation rather than another timed step; [evaluation](langfuse/05_evaluation_metrics_alerting.md). |
| Dataset / experiment | Reusable test inputs/expectations versus executions compared on that snapshot; [evaluation](langfuse/05_evaluation_metrics_alerting.md). |
| Calibration | Comparing evaluator judgments to reviewed human criteria and correcting disagreement; [evaluation](langfuse/05_evaluation_metrics_alerting.md). |
| Groundedness | Whether answer claims are supported by the supplied sources; [evaluation](langfuse/05_evaluation_metrics_alerting.md). |
| RAG | Retrieval of approved context before generation; [RAG lab](examples/01_rag_with_otel_and_langfuse.md). |
| Physical attempt | One actual provider request within a logical retrying workflow; [GenAI](opentelemetry/06_genai_and_llm_observability.md). |
| First chunk / first text | First provider message versus first user-visible text delta; [GenAI streaming](opentelemetry/06_genai_and_llm_observability.md). |
| Token usage | Available provider input/output consumption, excluding unknown estimates; [data model](langfuse/01_overview_data_model.md). |
| Agent step | One model decision iteration, which may request multiple tools; [agent lab](examples/02_multi_service_agent.md). |
| Idempotency | Repeating an operation identity/payload without repeating its intended effect; [agent lab](examples/02_multi_service_agent.md). |
| In-flight claim | Atomic ownership of running work before its result exists; [agent lab](examples/02_multi_service_agent.md). |
| Fencing | Rejecting stale owners using an authoritative ownership token/version; [agent lab](examples/02_multi_service_agent.md). |
| Outbox | Durable intent recorded with application state and delivered/reconciled separately; [RAG lab](examples/01_rag_with_otel_and_langfuse.md). |
| GA / preview / deprecated | Released availability / provisional behavior / discouraged or scheduled removal; [landscape](README.md#whats-changing). |
| Native histogram | Histogram sample carrying its bucket representation, requiring compatible aggregation, transport, storage and query support; [representation choice](opentelemetry/05_custom_metrics_alerting.md). |
| OTTL | OpenTelemetry Transformation Language used by Collector transforms; its language stability is separate from component stability; [production architecture](opentelemetry/03_production_architecture.md). |
| Score provenance | Evidence of which evaluator, rule or annotation produced a score; [evaluation](langfuse/05_evaluation_metrics_alerting.md). |
| Experiment identity | Stable experiment identifier shared deliberately by resumed or distributed workers, distinct from its display name; [evaluation](langfuse/05_evaluation_metrics_alerting.md). |
