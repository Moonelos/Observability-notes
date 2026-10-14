# OpenTelemetry Deployment Guide

> Deploy, connect, scale, secure, and upgrade OpenTelemetry Collectors without turning the telemetry path into an unmonitored production dependency.

[![OpenTelemetry](https://img.shields.io/badge/OpenTelemetry-Collector-F5A800.svg)](https://opentelemetry.io/docs/collector/)
[![Docker](https://img.shields.io/badge/Docker-Compose-2496ED.svg?logo=docker&logoColor=white)](https://docs.docker.com/compose/)
[![Kubernetes](https://img.shields.io/badge/Kubernetes-Deployment-326CE5.svg?logo=kubernetes&logoColor=white)](https://opentelemetry.io/docs/platforms/kubernetes/)

Last verified against official OpenTelemetry documentation and upstream
repositories on 2026-10-14. Examples pin Collector `0.157.0` and chart `0.168.0`; re-check the
release, distribution manifest, chart version, and upgrade notes before use.

---

## 📁 Contents

| File | Topic | Description |
| --- | --- | --- |
| [01_deployment_decisions.md](01_deployment_decisions.md) | Architecture and artifacts | Choose direct, agent, gateway, or agent-to-gateway; select Core, Contrib, Kubernetes, or a custom distribution; decide whether the Operator is justified. |
| [02_docker_compose.md](02_docker_compose.md) | Docker | Run and validate a pinned Collector image locally, expose only required ports, and understand what must change before production. |
| [03_kubernetes_installation.md](03_kubernetes_installation.md) | Kubernetes | Install with the upstream Helm chart or Operator, configure secrets, resources, probes, Services, disruption controls, and production-safe defaults. |
| [04_service_discovery_and_clients.md](04_service_discovery_and_clients.md) | Connectivity | Find Collector workloads and Services, choose the correct OTLP endpoint for each topology, configure applications, and verify end-to-end delivery. |
| [05_scaling_and_resilience.md](05_scaling_and_resilience.md) | Capacity and reliability | Scale stateless pipelines, isolate stateful processors, route tail-sampled traces correctly, size queues, and distinguish Collector saturation from backend saturation. |
| [06_security_operations_and_upgrades.md](06_security_operations_and_upgrades.md) | Operations | Protect trust boundaries, monitor the Collector itself, handle incidents, roll out configuration safely, and use a go-live checklist. |

---

## 🧭 Reading Order

1. **Deployment decisions** — decide what you are deploying and why.
2. **Docker Compose** — prove the Collector config and backend credentials in a small environment.
3. **Kubernetes installation** — convert the proven config into managed cluster resources.
4. **Service discovery and clients** — make workloads send to the right endpoint.
5. **Scaling and resilience** — add replicas and buffering without breaking stateful processing.
6. **Security, operations, and upgrades** — make the telemetry path supportable over time.

---

## 🗺️ Recommended Starting Point

For a typical Kubernetes environment:

```text
application SDKs
  -> ClusterIP Service on 4317 or 4318
  -> 3 stateless gateway Collector replicas
  -> authenticated, encrypted backend endpoint
```

Use the upstream **Collector Helm chart** unless the platform already operates
the OpenTelemetry Operator or needs its auto-instrumentation, sidecar injection,
or Target Allocator features. Add a DaemonSet tier only for node-local
collection such as container logs, host metrics, or a required local telemetry
hop. Add a separate trace-aware routing and sampling tier before enabling tail
sampling at scale.

---

## Milestones and stop points

Readers need basic Python and shell use plus the linked OTel pipeline lesson.
Chapter 2 provides a bounded local producer→Collector→backend proof; stop there
for transport practice. Chapters 3–4 bridge Kubernetes concepts and endpoints,
but their cluster actions require a disposable cluster and intended backend.
Chapters 5–6 explain capacity, trace ownership, tested local TLS/auth, incident
triage and release gates. Local tests do not certify cluster production readiness.

## What's changing

Checked 2026-10-14. The historical pair stays fixed so its examples remain
reproducible. Review changes before choosing a newer production baseline:

- **DEPRECATED / migration:** `loadbalancing` naming is migrating to
  `load_balancing`; validate the identifier with the target binary rather than
  copying aliases between versions. [Component source](https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/v0.157.0/exporter/loadbalancingexporter).
- **Released chart behavior:** current chart values include OTLP-based internal
  telemetry options, distinct from this pull-based metrics baseline. Recheck
  metrics ports and scrape configuration when changing chart versions.
  [Current values](https://github.com/open-telemetry/opentelemetry-helm-charts/blob/main/charts/opentelemetry-collector/values.yaml).
- **PREVIEW / feature gates:** Collector components and feature gates have
  independent stability. A released binary does not make every component GA.
  [Feature gate lifecycle](https://github.com/open-telemetry/opentelemetry-collector/blob/main/featuregate/README.md).
- **Deployment practice:** dedicated trace routing and node-local collection
  remain conditional tiers; use them when the state/permission owner requires
  them. [Gateway guidance](https://opentelemetry.io/docs/collector/deploy/gateway/).

## 📌 Prerequisites

- [OpenTelemetry concepts](../01_concepts.md) — signals, SDKs, exporters, and Collector pipelines.
- [Production architecture](../03_production_architecture.md) — processors, routing, redaction, sampling, and backend responsibilities.
- Access to the backend's documented OTLP endpoint, protocol, TLS requirements, authentication scheme, and quotas.
- For Kubernetes: a namespace, a secret-management path, resource quotas, NetworkPolicy support, and a way to scrape Collector internal metrics.

---

## 🔗 Official References

- [Install the Collector](https://opentelemetry.io/docs/collector/install/)
- [Collector distributions](https://opentelemetry.io/docs/collector/distributions/)
- [Collector deployment patterns](https://opentelemetry.io/docs/collector/deploy/)
- [OpenTelemetry Collector Helm chart](https://opentelemetry.io/docs/platforms/kubernetes/helm/collector/)
- [OpenTelemetry Operator](https://github.com/open-telemetry/opentelemetry-operator)
- [Scaling the Collector](https://opentelemetry.io/docs/collector/scaling/)
- [Collector internal telemetry](https://opentelemetry.io/docs/collector/internal-telemetry/)
- [Collector security guidance](https://opentelemetry.io/docs/security/config-best-practices/)

**Next**: [Part 1: Deployment Decisions](01_deployment_decisions.md)
