# Find Collector Services And Connect Applications

> **Who this is for**: Application and platform engineers who have a running Collector but need to identify its stable endpoint and prove that telemetry reaches the intended backend.

Complete **[Kubernetes Installation](03_kubernetes_installation.md)** or the
equivalent platform deployment first.

The following path connects the stable name to changing ready pods:

```mermaid
flowchart LR
    A[checkout-api] -->|HTTP 4318 and /v1/traces| S[otel-gateway DNS]
    S -->|Ready EndpointSlice address| G[Gateway pod]
    G -->|Authenticated HTTPS| B[Intended backend]
    N[App on node without ready agent] --> L[Agent Service with Local policy]
    L -->|No local endpoint| F[Connection fails]
```

DNS names the Service, while EndpointSlices identify its ready destinations.
The ordinary gateway can use remote ready pods. A Local Service intentionally
removes that fallback, so the app on an empty node fails even when other nodes
have healthy agents. Accepted spans prove A→G; sent spans and the exact backend
canary establish G→B. Check the failing boundary before changing selectors.

---

## 1. 🧭 Endpoint Follows Topology

The correct address is not always "the Collector Service":

| Collector shape | Application endpoint | Why |
| --- | --- | --- |
| Sidecar | `http://127.0.0.1:4317` or `:4318` | The Collector shares the pod network namespace. |
| DaemonSet agent | Node IP/host port, or a Service with same-node routing | Telemetry should stay on the node; a normal ClusterIP can send it elsewhere. |
| Gateway Deployment | ClusterIP Service DNS | The Service gives stable discovery and load distribution across replicas. |
| Outside the cluster | Authenticated TLS load balancer, Gateway API, or ingress that supports the chosen OTLP protocol | Cluster DNS is not reachable and the endpoint crosses a trust boundary. |
| Agent to gateway | Application to local agent; agent to gateway Service | Keeps app configuration local while centralizing backend policy. |

For a gateway Helm release with `fullnameOverride: otel-gateway` in namespace
`observability`, the normal in-cluster endpoints are:

```text
OTLP/gRPC  http://otel-gateway.observability.svc.cluster.local:4317
OTLP/HTTP  http://otel-gateway.observability.svc.cluster.local:4318
```

Do not assume that exact name for another chart release or Operator resource.
Read the created Service.

---

## 2. 🔍 Discover What Is Actually Installed

Start from the management layer:

```bash
# Helm-managed Collectors
helm list -A | grep -i opentelemetry

# Operator-managed Collectors
kubectl get opentelemetrycollectors.opentelemetry.io -A

# Collector-like workloads, regardless of installer
kubectl get deployments,daemonsets,statefulsets -A \
  -l app.kubernetes.io/name=opentelemetry-collector
```

Then inspect Services and their real backends:

```bash
kubectl --namespace observability get services \
  -l app.kubernetes.io/instance=otel-gateway

kubectl --namespace observability get service otel-gateway -o yaml

kubectl --namespace observability get endpointslices \
  -l kubernetes.io/service-name=otel-gateway \
  -o wide
```

If labels or names differ, search by known ports:

```bash
kubectl get services -A -o wide | grep -E 'otel|4317|4318'
kubectl get endpointslices -A | grep -i otel
```

A Service without ready EndpointSlice addresses cannot deliver telemetry. Fix
selectors or pod readiness before changing application SDKs.

The Operator normally creates Services by parsing receiver endpoints in the
Collector custom resource. Environment-variable expansion in a receiver port
can prevent that parsing; inspect the Operator events and generated Services
rather than assuming creation succeeded.

---

## 3. 🌐 Configure The Application

Set service identity independently from exporter transport:

```yaml
env:
  - name: OTEL_SERVICE_NAME
    value: checkout-api
  - name: OTEL_RESOURCE_ATTRIBUTES
    value: service.version=2026.07.24,deployment.environment.name=production
  - name: OTEL_EXPORTER_OTLP_ENDPOINT
    value: http://otel-gateway.observability.svc.cluster.local:4318
  - name: OTEL_EXPORTER_OTLP_PROTOCOL
    value: http/protobuf
```

The generic OTLP/HTTP endpoint is a base URL. Standards-compliant SDK exporters
append `/v1/traces`, `/v1/metrics`, or `/v1/logs`. A signal-specific endpoint
such as `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` normally needs the full
`/v1/traces` path. Confirm the chosen language SDK's precedence rules.

For gRPC:

```yaml
env:
  - name: OTEL_EXPORTER_OTLP_ENDPOINT
    value: http://otel-gateway.observability.svc.cluster.local:4317
  - name: OTEL_EXPORTER_OTLP_PROTOCOL
    value: grpc
```

Plaintext `http://` is reasonable only within an explicitly trusted cluster
boundary. Use `https://` and provide the appropriate CA when the connection
crosses namespaces, clusters, networks, or organizational trust boundaries as
required by policy.

Set signal-specific destinations only when the topology requires it:

```yaml
env:
  - name: OTEL_EXPORTER_OTLP_TRACES_ENDPOINT
    value: http://otel-gateway.observability.svc.cluster.local:4318/v1/traces
  - name: OTEL_EXPORTER_OTLP_METRICS_ENDPOINT
    value: http://otel-metrics.observability.svc.cluster.local:4318/v1/metrics
  - name: OTEL_EXPORTER_OTLP_PROTOCOL
    value: http/protobuf
```

Avoid putting backend credentials in applications when the Collector is the
credential boundary. Applications authenticate to the Collector when required;
the Collector holds separate least-privilege credentials for each backend.

---

## 4. 🔗 Connect To A DaemonSet Or Sidecar

A sidecar is straightforward:

```yaml
env:
  - name: OTEL_EXPORTER_OTLP_ENDPOINT
    value: http://127.0.0.1:4317
  - name: OTEL_EXPORTER_OTLP_PROTOCOL
    value: grpc
```

For a DaemonSet using a host port, inject the node IP:

```yaml
env:
  - name: OTEL_AGENT_HOST
    valueFrom:
      fieldRef:
        fieldPath: status.hostIP
  - name: OTEL_EXPORTER_OTLP_ENDPOINT
    value: http://$(OTEL_AGENT_HOST):4317
  - name: OTEL_EXPORTER_OTLP_PROTOCOL
    value: grpc
```

This assumes the agent listens on that node IP/port and NetworkPolicy, host
firewall, and CNI behavior permit access. Host ports also conflict if another
pod on the node already owns `4317` or `4318`.

A DaemonSet Service with `internalTrafficPolicy: Local` is another option. It
fails on a node without a ready local endpoint, which is often preferable to
silently sending node-local telemetry to another node. Test node drains and
agent rollout behavior explicitly.

> ⚠️ **Watch out:** A normal ClusterIP in front of a DaemonSet does not guarantee same-node delivery; node-local collection needs an explicit locality mechanism.

---

## 5. 📡 Know The Ports

Expose only ports used by a configured component:

| Port | Typical purpose | Exposure |
| --- | --- | --- |
| `4317/TCP` | OTLP/gRPC receiver | Applications/agents that use gRPC. |
| `4318/TCP` | OTLP/HTTP receiver | Applications/agents that use HTTP/protobuf or HTTP/JSON. |
| `8888/TCP` | Collector internal Prometheus metrics | Monitoring system only. |
| `13133/TCP` | `health_check` extension | Kubelet probes and restricted operations access. |
| `55679/TCP` | zPages, when explicitly enabled | Local/debug access only; never public by default. |
| `1777/TCP` | pprof, when explicitly enabled | Temporary restricted debugging only. |

Jaeger and Zipkin ports are not required when all clients use OTLP. Disable the
receivers, chart ports, Service ports, and NetworkPolicy allowances together.

OTLP/gRPC needs an HTTP/2-aware path. A load balancer that accepts TCP but pins
each long-lived client connection to one backend can produce uneven replica
load. OTLP/HTTP often works more predictably through existing HTTP
infrastructure, but protocol selection should follow SDK support, overhead,
proxy behavior, and backend requirements.

---

## 6. ✅ Verify Every Hop

Use a canary service name and unique attribute:

```text
service.name = otel-deployment-canary
deployment.environment.name = production
deployment.canary.id = <release-id>
```

Verify in this order:

1. Application exporter reports no repeated timeout or retry errors.
2. Service DNS resolves from the application pod.
3. Service has ready EndpointSlices.
4. Collector accepted counters rise for the signal.
5. Collector refused and enqueue-failed counters stay at zero.
6. Collector sent counters rise.
7. Backend query finds the canary with the expected resource attributes.

Useful cluster checks:

```bash
kubectl --namespace application exec deploy/checkout-api -- \
  getent hosts otel-gateway.observability.svc.cluster.local

kubectl --namespace observability logs deployment/otel-gateway \
  --since=10m --all-pods=true

kubectl --namespace observability port-forward service/otel-gateway 8888:8888
curl --silent http://127.0.0.1:8888/metrics | grep '^otelcol_'
```

The application image may not contain `getent`, `curl`, or TLS tools. Use an
approved ephemeral debug container or debug pod rather than modifying the
production image.

---

## 7. ⚠️ Common Client Mistakes

| Mistake | Result | Correction |
| --- | --- | --- |
| HTTP exporter points to `:4317` | Protocol errors or connection resets | Use `4318` for OTLP/HTTP. |
| gRPC exporter points to `:4318` | Unimplemented or malformed request errors | Use `4317` for OTLP/gRPC. |
| Signal-specific HTTP endpoint omits `/v1/traces` | Usually HTTP `404` | Add the signal path; generic base endpoints append it. |
| Application uses `localhost` for a gateway | It calls itself, not the Collector | Use Service DNS; reserve localhost for sidecars. |
| App and Collector use the same backend credential | Credential sprawl | Let the Collector own backend credentials. |
| Service name is empty or generic | Unusable backend grouping | Set stable `service.name`, version, and environment resource attributes. |
| Gateway Service is public by default | Telemetry injection and resource-exhaustion risk | Keep it internal; add authenticated TLS only for explicit external senders. |
| Readiness passes, so delivery is assumed healthy | Backend outages go unnoticed | Monitor receive/export/failure/queue metrics and query a canary. |

---

## Recap and practice

Choose an address reachable from the client's network namespace, then match
transport and signal path. Stable DNS and healthy endpoint membership are
separate conditions.

<details><summary>A generic HTTP base URL becomes a traces-specific URL without adding a path. Why 404?</summary>
The generic endpoint lets the SDK append /v1/traces. A signal-specific URL is
used as supplied; add /v1/traces before investigating Service selectors.
</details>

<details><summary>Would adding a remote ready agent repair Local Service routing?</summary>
No. Local deliberately restricts selection to the client's node. Restore a
local endpoint or choose a topology with remote fallback.
</details>

**Try it:** move checkout-api into another namespace. Choose the gateway's
namespace-qualified Service DNS name, verify its EndpointSlices, then send a
unique canary and distinguish accepted input from backend receipt.

<details><summary>Worked solution for try it</summary>

Use otel-gateway.observability.svc.cluster.local from the new namespace. Resolve it, inspect ready EndpointSlices, then require accepted input, acknowledged export and the exact canary at the intended backend. DNS success alone cannot establish a ready pod or exporter delivery.

</details>

## 🔗 Official References

- [OTLP exporter configuration](https://opentelemetry.io/docs/languages/sdk-configuration/otlp-exporter/)
- [OTLP exporter specification](https://opentelemetry.io/docs/specs/otel/protocol/exporter/)
- [Gateway deployment pattern](https://opentelemetry.io/docs/collector/deploy/gateway/)
- [Agent deployment pattern](https://opentelemetry.io/docs/collector/deploy/agent/)
- [Collector troubleshooting](https://opentelemetry.io/docs/collector/troubleshooting/)
- [Operator Collector documentation](https://github.com/open-telemetry/opentelemetry-operator/tree/main/docs/collector)

**Next**: [Part 5: Scaling And Resilience](05_scaling_and_resilience.md)
