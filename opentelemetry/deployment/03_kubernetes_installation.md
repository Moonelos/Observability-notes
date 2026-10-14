# Deploy The Collector On Kubernetes

> **Who this is for**: Readers who proved the local pipeline and now need a repeatable Collector installation.

Start with **[Deployment Decisions](01_deployment_decisions.md)** and prove the
pipeline against its backend with **[Docker Compose](02_docker_compose.md)**.

---

## 1. 🧭 Recommended Ownership Model

Use one Kubernetes workload for one operational job:

A **pod** is the scheduled group containing a process; a **Deployment** replaces
pods and maintains a replica count. A **Service** gives those changing pod
addresses one stable name and selects ready endpoints. A **DaemonSet** schedules
a node agent on each eligible node. A **namespace** groups names and access
policies; RBAC grants access to the Kubernetes API, not backend credentials.

This topology shows which process needs which permission:

```mermaid
flowchart LR
    A[Application pods] -->|OTLP 4317 or 4318| S[otel-gateway Service]
    N[Node agent DaemonSet] -->|OTLP| S
    F[Files on each node] -->|Node mounts| N
    S --> G1[Gateway 1]
    S --> G2[Gateway 2]
    S --> G3[Gateway 3]
    G1 -->|HTTPS and backend credential| B[Backend]
    G2 --> B
    G3 --> B
    G1 -.->|Metadata watch with RBAC| K[Kubernetes API]
```

The Service sends traffic to ready gateway pods; readiness does not establish
backend receipt. All gateways using Kubernetes attribute enrichment need the
API permission shown for G1. A pure transport gateway can remove that processor,
the preset and its API dependency. Node file mounts belong beside agents only.


Do not enable node file mounts, cluster-wide API permissions, application OTLP,
tail sampling, and every backend credential in one Collector merely because the
chart permits it. Separate workloads let you scale, secure, and roll them back
independently.

The baseline below installs a **stateless gateway Deployment** with the upstream
Collector Helm chart. It does not collect container logs or cluster metrics.

---

## First render a pinned baseline locally

Helm is a generator and release manager: values plus a chart produce Kubernetes
objects. Chart `0.168.0` declares Collector `0.157.0` as its appVersion. This
historical pair is the teaching baseline; it is not a claim about newest releases.
[Chart source](https://github.com/open-telemetry/opentelemetry-helm-charts/tree/opentelemetry-collector-0.168.0/charts/opentelemetry-collector).

From the repository root, before accessing any cluster:

```bash
helm repo add open-telemetry https://open-telemetry.github.io/opentelemetry-helm-charts
helm template otel-gateway open-telemetry/opentelemetry-collector \
  --namespace observability --version 0.168.0 \
  --values examples/local/deployment_gateway_values.yaml > /tmp/otel-gateway-rendered.yaml
```

Install PyYAML in a disposable Python environment, then extract the generated
Collector config (not the input values) from its ConfigMap:

```python
from pathlib import Path
import yaml
objects = list(yaml.safe_load_all(Path('/tmp/otel-gateway-rendered.yaml').read_text()))
configs = [o for o in objects if o and o['kind'] == 'ConfigMap']
assert len(configs) == 1
Path('/tmp/otel-gateway-collector.yaml').write_text(configs[0]['data']['relay'])
```

Run the exact Kubernetes image against the rendered configuration:

```bash
docker run --rm --env MY_POD_IP=127.0.0.1 \
  --env OTLP_BACKEND_ENDPOINT=https://otlp.example.com \
  --env OTLP_BACKEND_AUTHORIZATION='Bearer validation-placeholder' \
  --volume /tmp/otel-gateway-collector.yaml:/etc/otelcol/collector.yaml:ro \
  ghcr.io/open-telemetry/opentelemetry-collector-releases/opentelemetry-collector-k8s:0.157.0 \
  validate --config=/etc/otelcol/collector.yaml
```

Rendering and validation were executed locally with Helm 3.19.0 and the pinned
image (checked 2026-10-14). This validates artifact compatibility; it does not
verify cluster RBAC, CNI, DNS, readiness or backend receipt. Keep install commands
below behind a disposable-cluster gate. An install succeeds only after the same
canary proof as chapter 2 reaches the intended backend through the Service.

## 2. 🔒 Create Namespace And Secret Boundaries

Create a dedicated namespace through the cluster's GitOps path:

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: observability
  labels:
    pod-security.kubernetes.io/enforce: restricted
```

The Collector needs a backend credential, but the values file must not contain
its value. For a disposable test only:

```bash
kubectl --namespace observability create secret generic otel-backend \
  --from-literal=authorization='Bearer replace-me'
```

That command can expose the secret through shell history and audit/logging
systems. Production should use the organization's External Secrets, Secrets
Store CSI, sealed-secret, or equivalent GitOps-compatible secret path.

Give each Collector workload only its own backend credentials. A node log agent
does not need the same token as an LLM trace gateway unless the backend requires
it.

---

## 3. 📦 Install A Gateway With Helm

The upstream chart requires both an explicit `mode` and image repository. Save
the following as `gateway-values.yaml`:

```yaml
fullnameOverride: otel-gateway
mode: deployment

image:
  repository: ghcr.io/open-telemetry/opentelemetry-collector-releases/opentelemetry-collector-k8s
  tag: "0.157.0"
  pullPolicy: IfNotPresent

replicaCount: 3

presets:
  kubernetesAttributes:
    enabled: true
    extractAllPodLabels: false
    extractAllPodAnnotations: false

config:
  receivers:
    jaeger: null
    prometheus: null
    zipkin: null
    otlp:
      protocols:
        grpc:
          endpoint: ${env:MY_POD_IP}:4317
        http:
          endpoint: ${env:MY_POD_IP}:4318

  processors:
    memory_limiter:
      check_interval: 1s
      limit_percentage: 75
      spike_limit_percentage: 15
    batch:
      timeout: 5s
      send_batch_size: 512

  exporters:
    debug: null
    otlphttp/backend:
      endpoint: ${env:OTLP_BACKEND_ENDPOINT}
      headers:
        Authorization: ${env:OTLP_BACKEND_AUTHORIZATION}
      sending_queue:
        enabled: true
        num_consumers: 10
        queue_size: 2000
      retry_on_failure:
        enabled: true
        initial_interval: 5s
        max_interval: 30s
        max_elapsed_time: 15m

  service:
    extensions: [health_check]
    pipelines:
      traces:
        receivers: [otlp]
        processors: [memory_limiter, batch]
        exporters: [otlphttp/backend]
      metrics:
        receivers: [otlp]
        processors: [memory_limiter, batch]
        exporters: [otlphttp/backend]
      logs:
        receivers: [otlp]
        processors: [memory_limiter, batch]
        exporters: [otlphttp/backend]

extraEnvs:
  - name: OTLP_BACKEND_ENDPOINT
    value: https://otlp.example.com
  - name: OTLP_BACKEND_AUTHORIZATION
    valueFrom:
      secretKeyRef:
        name: otel-backend
        key: authorization

ports:
  otlp:
    enabled: true
  otlp-http:
    enabled: true
  jaeger-compact:
    enabled: false
  jaeger-thrift:
    enabled: false
  jaeger-grpc:
    enabled: false
  zipkin:
    enabled: false
  metrics:
    enabled: true
    containerPort: 8888
    servicePort: 8888
    protocol: TCP

resources:
  requests:
    cpu: 250m
    memory: 512Mi
  limits:
    cpu: "1"
    memory: 1Gi

useGOMEMLIMIT: true
terminationGracePeriodSeconds: 30

podSecurityContext:
  runAsNonRoot: true
  seccompProfile:
    type: RuntimeDefault

securityContext:
  allowPrivilegeEscalation: false
  readOnlyRootFilesystem: true
  capabilities:
    drop: [ALL]

podDisruptionBudget:
  enabled: true
  minAvailable: 2

topologySpreadConstraints:
  - maxSkew: 1
    topologyKey: topology.kubernetes.io/zone
    whenUnsatisfiable: ScheduleAnyway
    labelSelector:
      matchLabels:
        app.kubernetes.io/instance: otel-gateway
  - maxSkew: 1
    topologyKey: kubernetes.io/hostname
    whenUnsatisfiable: DoNotSchedule
    labelSelector:
      matchLabels:
        app.kubernetes.io/instance: otel-gateway

autoscaling:
  enabled: false

serviceMonitor:
  enabled: false

networkPolicy:
  enabled: false
```

Before using this file:

- Replace the backend endpoint and remove unsupported signal pipelines.
- Add redaction and routing policy from
  [Production Architecture](../03_production_architecture.md).
- Confirm the Kubernetes distribution contains every component with its
  upstream manifest or `components` command.
- Verify the actual chart labels before relying on the example topology spread
  selectors. `helm template` is the source of truth.
- Enable `serviceMonitor` only if the Prometheus Operator CRD exists and the
  monitor labels match the Prometheus selector.
- Do not enable `networkPolicy` until required DNS and backend egress have been
  modeled; an empty or incorrect egress policy can silently stop export.

Work the disruption controls with three gateways. `minAvailable: 2` lets a
cooperative voluntary eviction remove at most one currently healthy pod; an
attempt to evict a second is blocked until replacement is Ready. A node crash
can still remove two pods simultaneously because involuntary failure bypasses
the PDB. A PDB is an eviction budget, not a recovery-capacity guarantee.

The hostname rule is hard: DoNotSchedule leaves a replacement Pending when no
eligible host can keep the selected replicas within maxSkew=1. With three
healthy eligible hosts, three replicas can occupy one per host; with only two
hosts, the 2/1 distribution still meets maxSkew=1, so this rule is not strict
one-pod-per-host anti-affinity. The zone rule is soft: ScheduleAnyway permits
a less even zone placement to keep pods schedulable. Inspect actual placement
and capacity after a failure; these fields do not create missing hosts or zones.
Run the N-1 throughput calculation in chapter 5 before interpreting three Ready
pods as high availability.

The Kubernetes attributes preset creates RBAC and adds the processor to enabled
pipelines. It deliberately does not copy every pod label or annotation because
that creates cardinality, privacy, and cost risks.

> ⚠️ **Watch out:** The chart merges your `config` into defaults; explicitly set unused default receivers, exporters, pipelines, and ports to `null` or disabled, then inspect the rendered configuration.

---

## 4. ✅ Render, Validate, And Install

Pin the chart version independently from the Collector image:

```bash
helm repo add open-telemetry \
  https://open-telemetry.github.io/opentelemetry-helm-charts
helm repo update

helm search repo open-telemetry/opentelemetry-collector --versions

export OTEL_CHART_VERSION="0.168.0"

helm template otel-gateway open-telemetry/opentelemetry-collector \
  --namespace observability \
  --version "${OTEL_CHART_VERSION}" \
  --values gateway-values.yaml > /tmp/otel-gateway-rendered.yaml
```

Review the rendered Deployment, ConfigMap, RBAC, Services, probes, environment
variables, security context, and labels. Validate the embedded Collector config
with the pinned Collector image in CI; the fact that Helm rendered YAML does not
mean the Collector recognizes every component or field.

Install only the reviewed chart version:

```bash
helm upgrade --install otel-gateway \
  open-telemetry/opentelemetry-collector \
  --namespace observability \
  --version "${OTEL_CHART_VERSION}" \
  --values gateway-values.yaml \
  --atomic \
  --timeout 10m

kubectl --namespace observability rollout status deployment/otel-gateway
kubectl --namespace observability get pods,services,endpointslices \
  -l app.kubernetes.io/instance=otel-gateway
```

`--atomic` rolls the Helm release back when Kubernetes readiness fails. It
cannot detect a logically wrong backend route. Send canary telemetry and verify
the backend after every install.

---

## 5. 🛠️ Use The Operator Only When Its Capabilities Are Needed

The OpenTelemetry Operator manages Collector and auto-instrumentation resources.
Its upstream manifest installation requires cert-manager. The Operator creates
Kubernetes Services from parseable receiver endpoints and supports Deployment,
DaemonSet, StatefulSet, and sidecar modes.

An equivalent gateway custom resource starts like this:

```yaml
apiVersion: opentelemetry.io/v1beta1
kind: OpenTelemetryCollector
metadata:
  name: gateway
  namespace: observability
spec:
  mode: deployment
  replicas: 3
  image: ghcr.io/open-telemetry/opentelemetry-collector-releases/opentelemetry-collector-k8s:0.157.0
  upgradeStrategy: none
  env:
    - name: OTLP_BACKEND_ENDPOINT
      value: https://otlp.example.com
    - name: OTLP_BACKEND_AUTHORIZATION
      valueFrom:
        secretKeyRef:
          name: otel-backend
          key: authorization
  resources:
    requests:
      cpu: 250m
      memory: 512Mi
    limits:
      cpu: "1"
      memory: 1Gi
  config:
    receivers:
      otlp:
        protocols:
          grpc:
            endpoint: 0.0.0.0:4317
          http:
            endpoint: 0.0.0.0:4318
    processors:
      memory_limiter:
        check_interval: 1s
        limit_percentage: 75
        spike_limit_percentage: 15
      batch:
        timeout: 5s
    exporters:
      otlphttp/backend:
        endpoint: ${env:OTLP_BACKEND_ENDPOINT}
        headers:
          Authorization: ${env:OTLP_BACKEND_AUTHORIZATION}
    service:
      pipelines:
        traces:
          receivers: [otlp]
          processors: [memory_limiter, batch]
          exporters: [otlphttp/backend]
```

`upgradeStrategy: none` keeps Collector image/config migration under your
release process. If the platform intentionally uses automatic upgrades, test
the Operator's migration behavior and set that policy explicitly.

The Operator does not fully validate arbitrary Collector configuration. An
accepted custom resource can still create a crash-looping Collector. Validate
the config against the exact image before applying the CR.

Use the Operator when at least one of these is an owned requirement:

- language auto-instrumentation injection through `Instrumentation`;
- sidecar Collector injection;
- Prometheus Target Allocator;
- an established platform API based on `OpenTelemetryCollector`;
- Operator-managed Service generation and upgrade behavior.

Otherwise, the Helm chart keeps the ownership chain shorter.

---

## 6. 📐 DaemonSet And Cluster Collector Differences

For node-local collection, this is a **preset fragment**, not a complete
agent-to-gateway deployment. Add an OTLP exporter to the gateway, replace the
debug exporter in each enabled pipeline and validate the merged configuration
before installing a second release:

```yaml
fullnameOverride: otel-node-agent
mode: daemonset

image:
  repository: ghcr.io/open-telemetry/opentelemetry-collector-releases/opentelemetry-collector-k8s
  tag: "0.157.0"

presets:
  logsCollection:
    enabled: true
    includeCollectorLogs: false
  hostMetrics:
    enabled: true
  kubeletMetrics:
    enabled: true
  kubernetesAttributes:
    enabled: true

service:
  enabled: true
  internalTrafficPolicy: Local
```

The presets add volumes, mounts, receivers, processors, and RBAC. Inspect all of
them. Container log collection may require host filesystem permissions; do not
copy the gateway's restricted security context blindly and then disable
security controls until it starts.

Run cluster-level receivers separately. A receiver that watches the whole
cluster may emit duplicate telemetry from every replica unless its specific
implementation or chart preset uses leader election.

---

## 7. ⚠️ Kubernetes Failure Modes

| Symptom | Likely cause | Check |
| --- | --- | --- |
| `CrashLoopBackOff` immediately | Invalid config or missing component | Previous container logs, rendered ConfigMap, exact image `components`, and `validate`. |
| Ready pods, no backend data | Wrong endpoint/protocol/auth, blocked egress, or backend rejection | Export failure metrics and logs, DNS/TLS from a debug pod, backend ingest view. |
| Some applications export, others time out | Wrong namespace DNS, NetworkPolicy, mesh policy, or DaemonSet locality | Resolve the Service from the failing pod and test the correct port. |
| Duplicate node or cluster metrics | A scraper was replicated without sharding or leader election | Receiver ownership, targets per replica, and resource attributes. |
| Pods are OOM-killed | Memory limit below working set, queue/tail-sampling growth, or limiter too late | Memory, queue, receive rate, batch size, and processor order. |
| Rollout drops telemetry | No drain time, only in-memory queues, too many simultaneous disruptions | PDB, rollout strategy, termination grace, queue persistence, and exporter latency. |
| Service has no endpoints | Selector mismatch or pods not Ready | Service selector, pod labels, EndpointSlices, and readiness events. |

---

## Recap and practice

Values generate objects; the rendered ConfigMap configures the exact binary.
Kubernetes readiness only establishes that the process can serve its probe.

<details><summary>Helm --atomic succeeds but the canary is missing and send failures rise. Accept the release?</summary>
No. Atomic rollback watches Kubernetes readiness, not logical delivery. Diagnose
the exact rendered config and export failure, then restore the prior complete
bundle if the canary gate fails.
</details>

<details><summary>Why does the node-agent preset fragment not prove forwarding?</summary>
It names collection presets and a Service, but omits an exporter/pipeline to the
gateway. Chart defaults can still export only to debug. Inspect merged output.
</details>

**Try it:** remove the gRPC receiver from the values. Disable its Service port,
render again and assert both the listener and port are absent. Explain why
changing only one of them leaves a misleading or unreachable endpoint.

<details><summary>Worked solution for try it</summary>

Set receivers.otlp.protocols.grpc to null and ports.otlp.enabled to false;
omitting the key would let chart defaults restore the receiver. Render again and inspect both the Collector ConfigMap and Service/container ports. A remaining port advertises a listener that does not exist; a remaining listener creates an unintended access surface.

</details>

## 🔗 Official References

- [OpenTelemetry Collector Helm chart](https://opentelemetry.io/docs/platforms/kubernetes/helm/collector/)
- [Kubernetes Collector components](https://opentelemetry.io/docs/platforms/kubernetes/collector/components/)
- [Kubernetes getting started](https://opentelemetry.io/docs/platforms/kubernetes/getting-started/)
- [OpenTelemetry Operator](https://github.com/open-telemetry/opentelemetry-operator)
- [Operator Collector custom resource](https://github.com/open-telemetry/opentelemetry-operator/tree/main/docs/collector)
- [Collector chart values](https://github.com/open-telemetry/opentelemetry-helm-charts/blob/main/charts/opentelemetry-collector/values.yaml)
- [Collector chart upgrade notes](https://github.com/open-telemetry/opentelemetry-helm-charts/blob/main/charts/opentelemetry-collector/UPGRADING.md)

**Next**: [Part 4: Service Discovery And Client Configuration](04_service_discovery_and_clients.md)
