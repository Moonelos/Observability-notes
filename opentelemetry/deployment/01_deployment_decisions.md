# Deployment Decisions: Topology, Distribution, and Installer

> **Who this is for**: Platform and application engineers who understand an OpenTelemetry pipeline but have not yet chosen how to run the Collector.

Start with the pipeline in **[OpenTelemetry concepts](../01_concepts.md)**.
Assumed knowledge is basic Python and shell use. A receiver accepts telemetry,
a processor changes it, and an exporter sends it onwards. This path teaches
container and cluster deployment concepts as they become necessary.

---

## 1. 🧭 Start With The Failure Boundary

The Collector is a **service that transports telemetry**. It is not the backend
that stores and queries telemetry, and it is not part of the application request
path unless the application uses a blocking exporter incorrectly.

Choose a topology by asking where a failure may affect telemetry:

| Topology | Use it when | Main cost or risk |
| --- | --- | --- |
| SDK directly to backend | Development, a small trusted environment, or a managed backend that explicitly recommends it | Credentials and routing policy are copied into every workload; backend changes require workload changes. |
| Sidecar | One Collector failure must be isolated to one pod, or `localhost` is a hard requirement | Highest pod and configuration overhead; every replica consumes resources. |
| DaemonSet agent | Collecting node-local logs/metrics, using host paths, or giving workloads a node-local endpoint | One failed agent affects its node; cluster-wide receivers can produce duplicates. |
| Gateway Deployment | Central routing, redaction, credentials, batching, or fan-out for many workloads | A shared dependency that needs load balancing, capacity planning, and at least two failure-domain-separated replicas. |
| Agent to gateway | Node-local collection plus central policy, or separate cluster and backend trust boundaries | Two Collector tiers to configure, monitor, and upgrade. |

A strong default for application traces and application-emitted metrics is a
gateway Deployment. Use a DaemonSet for work that is genuinely node-local, not
because "agents are more production-like."

The diagram separates a machine-local reader from a shared transport service:

```mermaid
flowchart LR
    A[Application checkout-api] -->|OTLP spans| G[Gateway replicas]
    N[Node agent] -->|Container log records| G
    F[Files on this node] -->|Read local paths| N
    G -->|Central credentials| B[Backend]
```

Moving the gateway leaves the files on their original node. Therefore adding
three gateways cannot replace the node agent: those processes have no access to
that node's paths. A sidecar instead runs beside one application in its pod;
it buys pod-level isolation at the cost of one Collector for every pod.


> 💡 **Key insight:** Deployment shape follows component ownership: node scrapers belong near nodes, while routing and backend credentials belong in a shared gateway.

---

## 2. 📦 Choose A Collector Distribution

A **distribution** is a Collector binary and container image containing a
specific set of components. Configuration cannot enable a component that the
binary does not contain.

The upstream project publishes these distributions:

| Distribution | Official artifact example | Choose it when |
| --- | --- | --- |
| Core | `otel/opentelemetry-collector:0.157.0` | A small OTLP-focused pipeline only needs Core components. |
| Contrib | `otel/opentelemetry-collector-contrib:0.157.0` | You need the broadest upstream receiver, processor, exporter, connector, or extension set. This is convenient for local testing and non-Kubernetes hosts. |
| Kubernetes | `ghcr.io/open-telemetry/opentelemetry-collector-releases/opentelemetry-collector-k8s:0.157.0` | You run on Kubernetes and its component manifest includes everything in your config. |
| OTLP | `ghcr.io/open-telemetry/opentelemetry-collector-releases/opentelemetry-collector-otlp:0.157.0` | The Collector only receives and exports OTLP with a deliberately narrow component surface. |
| eBPF profiling | Upstream `otelcol-ebpf-profiler` release artifact | A dedicated Linux node agent collects profiles with the eBPF profiler receiver. Its elevated host access is a reason to keep it separate from general telemetry gateways. |
| Custom | Your registry, built with the OpenTelemetry Collector Builder | You need a minimized, reviewed component set or an internal component. You also accept responsibility for building and patching it. |

Docker Hub and GHCR are both official publication paths. Mirror the chosen
image into an approved registry when your supply-chain or availability policy
requires it.

Inspect the binary before deploying a configuration:

```bash
COLLECTOR_IMAGE="otel/opentelemetry-collector-contrib:0.157.0"

docker run --rm "${COLLECTOR_IMAGE}" components
```

Then compare the output with every component ID in the config. Check the
distribution's upstream `manifest.yaml` in code review as well; component
availability and stability can change independently.

Use Contrib to discover a working pipeline, then consider Kubernetes or a custom
distribution to reduce the production attack and maintenance surface. Do not
select Core only because its image is smaller if the resulting config cannot
start.

---

## 3. 🛠️ Pin And Verify The Artifact

Never run `latest` in production. Pin three independently versioned artifacts:

1. Collector image version and, after promotion, image digest.
2. Helm chart version or Operator version.
3. Collector configuration revision.

The Collector's component versions move quickly and can include breaking config
changes. A chart upgrade can also change Services, probes, security defaults,
or generated Collector config without changing your values file.

Official release images are signed. A release-gate can verify an image with
Cosign:

```bash
COLLECTOR_VERSION="0.157.0"
COLLECTOR_IMAGE="ghcr.io/open-telemetry/opentelemetry-collector-releases/opentelemetry-collector-contrib:${COLLECTOR_VERSION}"

cosign verify \
  --certificate-identity="https://github.com/open-telemetry/opentelemetry-collector-releases/.github/workflows/base-release.yaml@refs/tags/v${COLLECTOR_VERSION}" \
  --certificate-oidc-issuer="https://token.actions.githubusercontent.com" \
  "${COLLECTOR_IMAGE}"
```

After verification, record the registry digest and deploy
`image@sha256:<digest>`. Keep the human-readable version in release metadata so
operators can identify it without reverse-looking up a digest.

---

## 4. 📐 Helm, Operator, Or Raw Manifests

These mechanisms install the same Collector process. The choice is about who
reconciles Kubernetes objects and how much cluster-level machinery you want.

| Method | Default decision | Use it when | Avoid it when |
| --- | --- | --- | --- |
| Upstream Collector Helm chart | **Recommended baseline** | GitOps or Helm already owns releases; you want explicit Deployments, DaemonSets, Services, RBAC, probes, and values. | Another controller must manage Collector and instrumentation CRs as one API. |
| OpenTelemetry Operator | Adopt deliberately | You need `OpenTelemetryCollector` and `Instrumentation` CRs, sidecar or auto-instrumentation injection, automatic Service generation, or the Prometheus Target Allocator. | You only need one gateway and do not want CRDs, admission webhooks, cert-manager, or another controller lifecycle. |
| Raw manifests/Kustomize | Exception | Organization policy forbids Helm and Operators, or a platform abstraction already generates resources. | You would be manually reproducing chart behavior without tests. |

The guide cannot infer whether a live cluster already uses the Operator. Check:

```bash
kubectl get crd \
  opentelemetrycollectors.opentelemetry.io \
  instrumentations.opentelemetry.io

kubectl get deployments -A \
  -l app.kubernetes.io/name=opentelemetry-operator

kubectl get opentelemetrycollectors.opentelemetry.io -A
helm list -A | grep -i opentelemetry
```

Interpret the result:

- Missing CRDs and no operator Deployment: the Operator is not installed.
- CRDs alone: they may be left over; find the controller before creating CRs.
- A running operator plus managed CRs: follow the owning platform team's
  Operator version and upgrade policy.
- A Helm Collector release without Operator CRs: manage the Collector with the
  Collector chart.

Do not install the Operator only to deploy one ordinary gateway. It requires a
cluster-scoped lifecycle, and the upstream manifest installation requires
cert-manager.

---

## 5. 🔀 Separate Collection Jobs That Scale Differently

One config can technically contain every receiver. That does not mean one
workload should:

| Work | Recommended owner | Why |
| --- | --- | --- |
| Receive application OTLP | Replicated gateway or local agent | Scales with application telemetry volume. |
| Read container log files | DaemonSet | Requires node-local host paths and checkpoints. |
| Scrape kubelet/host metrics | DaemonSet | Each agent should own its node. |
| Collect Kubernetes cluster metrics/events | One logical active instance or leader-elected set | Multiple independent scrapers duplicate data. |
| Prometheus target scraping | Sharded collectors or Operator Target Allocator | Replicating the same scrape config duplicates samples. |
| Tail sample traces | Dedicated stateful-in-memory processing tier behind trace-aware routing | Every span for one trace must reach the same decision maker. |

Split workloads when their permissions, scaling keys, failure domains, or
statefulness differ. This is easier to operate than one privileged "collector
of everything."

---

## 6. ✅ Decision Record

Before writing manifests, commit a short answer for every row:

| Decision | Required answer |
| --- | --- |
| Signals | Which of traces, metrics, logs, and profiles enter this workload? |
| Sources | Applications, agents, files, nodes, Kubernetes API, or external scrapes? |
| Topology | Direct, sidecar, DaemonSet, gateway, or agent-to-gateway? |
| Distribution | Exact image repository, version, digest, and required components? |
| Installer | Helm chart, Operator, or platform-managed raw manifests? |
| Endpoint | OTLP/gRPC `4317`, OTLP/HTTP `4318`, TLS name, and discovery path? |
| Backends | Endpoint, protocol, auth, quotas, and data residency per signal? |
| Data policy | Which attributes or bodies must be removed before each backend? |
| Reliability | Queue duration, restart durability, acceptable data loss, and failure behavior? |
| Scaling | Stateless, scraper-sharded, or trace-affine? Which metrics trigger scaling? |
| Ownership | Team, on-call, dashboard, alerts, runbook, and change approval path? |

If any answer is "whatever the default does," resolve it before production.

---

## Predict the owner

A team needs central backend credentials and log checkpoints that survive gateway
changes. Put application OTLP and credentials at the gateway; put file readers
and checkpoints on a node agent. A sidecar is justified when the application
requires localhost or pod-level isolation, rather than node-wide collection.

## Recap and check yourself

Topology follows state, permissions and failure boundaries. Component inclusion
comes from the binary; activation comes from configuration.

<details><summary>Can a Helm value add a missing receiver to Core?</summary>
No. Values configure the installed binary; select or build a distribution that
contains the receiver and validate the actual configuration with that binary.
</details>

<details><summary>Why keep a chart version beside the image version?</summary>
The chart generates ports, probes, RBAC and configuration independently of the
binary. A change in either artifact can break a previously working route.
</details>

## 🔗 Official References

- [Collector distributions](https://opentelemetry.io/docs/collector/distributions/)
- [Install with Docker](https://opentelemetry.io/docs/collector/install/docker/)
- [Collector deployment patterns](https://opentelemetry.io/docs/collector/deploy/)
- [OpenTelemetry Collector Builder](https://opentelemetry.io/docs/collector/extend/ocb/)
- [Collector image signature verification](https://github.com/open-telemetry/opentelemetry-collector#verifying-images)
- [OpenTelemetry Operator](https://github.com/open-telemetry/opentelemetry-operator)

**Next**: [Part 2: Docker Compose](02_docker_compose.md)
