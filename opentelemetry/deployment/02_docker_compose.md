# Run The Collector With Docker Compose

> **Who this is for**: Engineers who want a reproducible Collector deployment for local development, integration tests, or a small single-host environment.

Read **[Deployment Decisions](01_deployment_decisions.md)** first so the image
and topology are intentional.

---

## 1. Prove delivery before hardening

A container packages a process and its filesystem dependencies. Compose describes
several such processes and the network names between them. Neither packaging
method proves telemetry delivery. First establish the same process-level path
with a local backend you control; then package it.

The lab below runs an official **Contrib 0.157.0** binary and a small loopback
HTTP receiver. Obtain the matching release for your OS from the
[official release](https://github.com/open-telemetry/opentelemetry-collector-releases/releases/tag/v0.157.0).
It needs Python 3 and free ports 19418, 19433, 19480 and 19488. From the repository root:

```bash
python3 examples/local/deployment_canary.py /absolute/path/to/otelcol-contrib
```

The [complete lab](../../examples/local/deployment_canary.py) generates a
minimal traces-only config, validates it with that binary, starts the Collector,
and posts one named OTLP/JSON span. JSON is an OTLP wire encoding; this stdlib
producer keeps the first transport proof independent of an SDK installation.
The backend records the complete decoded request in memory. It is a test
receiver, with no storage/query guarantee beyond this bounded process run.

Watch where success is established in this sequence:

```mermaid
sequenceDiagram
    participant P as deployment-smoke-test
    participant C as Collector 0.157.0
    participant B as Controlled local backend
    P->>C: POST /v1/traces, trace ID ending 02
    C-->>P: 200 accepted
    C->>B: Export OTLP request
    B-->>C: 200 with empty OTLP response
    Note over B: Assert exact trace ID and service resource
```

The response to the producer proves ingress; it can precede backend acceptance
because the exporter queue decouples these actions. The sent counter proves an
export was acknowledged. The assertion at the backend proves the intended span
actually crossed the whole path. The lab expects `backend receipt=1`, then
injects 503 and 401 to show why ingress alone is insufficient. Its final metrics
show three accepted spans, two sent spans and failed export attempts. A 503 can
recover on retry; a 401 requires repairing credentials and is permanently
rejected in this pinned version.

This first lab proves only HTTP traces and the pinned binary. The larger config
below supports gRPC and all three stable signals; those paths require their own
producer/backend checks. TLS ingress is exercised in chapter 6. Local receipt
does not certify a real vendor backend or Kubernetes availability.

---

## 2. 🛠️ Collector Configuration

Save this as `collector.yaml`. It receives all three stable signals, protects
memory, batches data, retries temporary backend failures, exposes health and
internal metrics, and exports over OTLP/HTTP.

```yaml
extensions:
  health_check:
    endpoint: 0.0.0.0:13133

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
    limit_mib: 768
    spike_limit_mib: 192
  batch:
    timeout: 5s
    send_batch_size: 512

exporters:
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
  telemetry:
    metrics:
      level: normal
      readers:
        - pull:
            exporter:
              prometheus:
                host: 0.0.0.0
                port: 8888
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
```

Adapt this before use:

- Remove pipelines the backend does not accept.
- Add required redaction before `batch`; see
  [Production Architecture](../03_production_architecture.md).
- Use the backend's exact endpoint and authentication header. Some backends use
  separate endpoints or credentials per signal.
- Keep `memory_limiter` first. Its limit must stay below the container's memory
  limit so the process can shed load before the runtime is killed.
- Calculate queue size from measured batch size and tolerated outage; a larger
  queue consumes more memory and does not repair a slow backend.

> ⚠️ **Watch out:** A health-check response only proves that the Collector process is running; it does not prove that the backend is accepting telemetry.

---

## 3. 📦 Compose The Container

Save this as `compose.yaml` next to `collector.yaml`:

```yaml
services:
  otel-collector:
    image: otel/opentelemetry-collector-contrib:0.157.0
    command:
      - --config=/etc/otelcol/collector.yaml
    restart: unless-stopped
    environment:
      OTLP_BACKEND_ENDPOINT: ${OTLP_BACKEND_ENDPOINT:?set OTLP_BACKEND_ENDPOINT}
      OTLP_BACKEND_AUTHORIZATION: ${OTLP_BACKEND_AUTHORIZATION:?set OTLP_BACKEND_AUTHORIZATION}
    volumes:
      - ./collector.yaml:/etc/otelcol/collector.yaml:ro
    ports:
      - 127.0.0.1:4317:4317
      - 127.0.0.1:4318:4318
      - 127.0.0.1:13133:13133
      - 127.0.0.1:8888:8888
    stop_grace_period: 30s
```

The loopback bindings prevent another machine from sending arbitrary telemetry
to the development Collector. Containers on the same Compose network should
send to `otel-collector:4317` or `otel-collector:4318`, not the host mapping.

Provide credentials without committing them:

```bash
export OTLP_BACKEND_ENDPOINT="https://otlp.example.com"
export OTLP_BACKEND_AUTHORIZATION="Bearer replace-from-secret-store"

docker compose config --quiet
docker compose up -d
```

`docker compose config --quiet` validates without printing the expanded model.
The non-quiet command can disclose credentials; do not use it in shared logs. In a real deployment, inject the values from
the platform's secret store instead of a checked-in `.env` file.

---

## 4. ✅ Validate Before Starting

Run the exact production image against the exact config:

```bash
docker run --rm \
  --env OTLP_BACKEND_ENDPOINT="https://otlp.example.com" \
  --env OTLP_BACKEND_AUTHORIZATION="Bearer validation-placeholder" \
  --volume "${PWD}/collector.yaml:/etc/otelcol/collector.yaml:ro" \
  otel/opentelemetry-collector-contrib:0.157.0 \
  validate --config=/etc/otelcol/collector.yaml
```

Then inspect startup and health:

```bash
docker compose logs --tail=100 otel-collector
curl --fail --silent --show-error http://127.0.0.1:13133/
curl --fail --silent --show-error http://127.0.0.1:8888/metrics \
  | grep '^otelcol_'
```

Configure a local application with one protocol at a time:

```bash
# OTLP/HTTP base endpoint. The SDK appends /v1/traces, /v1/metrics, or /v1/logs.
export OTEL_EXPORTER_OTLP_ENDPOINT="http://127.0.0.1:4318"
export OTEL_EXPORTER_OTLP_PROTOCOL="http/protobuf"
export OTEL_SERVICE_NAME="deployment-smoke-test"
```

Success requires evidence at both boundaries:

- Collector receive counters increase.
- Collector export counters increase without sustained failures.
- The backend can find `service.name=deployment-smoke-test`.

Container logs alone are not proof of end-to-end delivery.

---

## 5. 🗄️ Add A Persistent Sending Queue Only Deliberately

An in-memory sending queue loses buffered telemetry when the container restarts.
If restart durability is required, use the Contrib `file_storage` extension and
a persistent volume:

```yaml
extensions:
  health_check:
    endpoint: 0.0.0.0:13133
  file_storage:
    directory: /var/lib/otelcol

exporters:
  otlphttp/backend:
    endpoint: ${env:OTLP_BACKEND_ENDPOINT}
    headers:
      Authorization: ${env:OTLP_BACKEND_AUTHORIZATION}
    sending_queue:
      enabled: true
      storage: file_storage
      queue_size: 2000

service:
  extensions: [health_check, file_storage]
```

Mount storage:

```yaml
services:
  otel-collector:
    volumes:
      - ./collector.yaml:/etc/otelcol/collector.yaml:ro
      - collector-data:/var/lib/otelcol

volumes:
  collector-data:
```

Verify that the image's non-root user can write the volume. Do not "fix"
permission errors by permanently running the Collector as root. Initialize the
volume ownership once, bound disk use, monitor free space, and test recovery by
stopping the backend, enqueueing telemetry, restarting the Collector, and
restoring the backend.

A persistent queue is a write-ahead log, not an unlimited durable message bus.
It can still lose data when the disk fails, fills, is deleted, or the retry
window expires.

---

The persistence lifecycle below explains why restart durability needs the same
volume, rather than merely the same container name:

```mermaid
sequenceDiagram
    participant P as deployment-smoke-test
    participant C as Collector
    participant D as collector-data volume
    participant B as Backend
    P->>C: Span while backend returns 503
    C->>D: Persist queued request
    Note over C: Process restarts
    D->>C: Recover from the same volume
    C->>B: Retry after backend recovers
    B-->>C: Acknowledge receipt
```

Without disk storage, the restart deletes the queued request. With a deleted or
unmounted volume, the new process cannot recover it either. Restoring storage
only restores pending work: receipt still depends on retry policy, valid
credentials and backend recovery. Run the bounded local persistence variant to exercise this sequence:

```bash
python3 examples/local/deployment_canary.py /absolute/path/to/otelcol-contrib --persistent
```

It restarts the Collector while the backend returns 503, reuses the same
file-storage directory, restores the backend, and asserts receipt of trace 03.
Counters reset on restart, so backend receipt is the durable cross-process
proof. This tests process restart with retained storage; it does not test full
disk, deleted volume, crash corruption or format downgrade.

## Recap, retrieval and try it

Separate process health, accepted input, acknowledged export and backend receipt.
A single-host deployment remains one host failure domain.

<details><summary>Health is 200 and accepted spans rise; sent spans stay flat. Is delivery proven?</summary>
No. Ingress works, but export is blocked or rejected. Inspect the queue, export
failures and endpoint/TLS/auth, then require the canary at the intended backend.
</details>

<details><summary>Does a persistent queue survive deletion of its volume?</summary>
No. The bytes belong to the volume, not the logical Collector name. Recovery
requires the retained volume and a compatible process/configuration.
</details>

**Try it:** change the 503 interval in the lab to exceed the five-second retry
window. Predict which span will never receive a backend receipt; inspect the
Collector log and compare accepted versus sent counts. Do not infer delivery
from the producer's 200 response.

## 6. ⚠️ Production Gaps

Before moving this single-host pattern into production, answer:

| Gap | Required production decision |
| --- | --- |
| Availability | Multiple instances and a protocol-aware load balancer, or an accepted single-host outage. |
| TLS on ingress | TLS or mTLS when traffic crosses a trust boundary. |
| Authentication | Prevent untrusted clients from consuming telemetry capacity or injecting false data. |
| Secrets | Platform secret store, rotation, and least-privilege backend token. |
| Resource isolation | CPU/memory limits, disk quota, and noisy-neighbor protection. |
| Monitoring | Scrape `:8888`, alert on refusal, enqueue failure, send failure, queue saturation, restarts, and memory pressure. |
| Upgrade | Pinned image digest, config validation, canary, drain behavior, and rollback. |
| Stateful processing | Trace-aware routing before tail sampling or span-to-metrics aggregation. |

For Kubernetes, implement those controls through the chart or Operator rather
than translating Compose line by line.

---

<details><summary>Worked solution for try it</summary>

The producer still receives 200, but trace 03 exceeds the retry window and never receives a backend receipt. Accepted input therefore exceeds sent output; a later backend recovery cannot recreate permanently dropped work. Emit a new canary to prove the restored route.

</details>

## 🔗 Official References

- [Install the Collector with Docker](https://opentelemetry.io/docs/collector/install/docker/)
- [Collector configuration](https://opentelemetry.io/docs/collector/configuration/)
- [Collector internal telemetry](https://opentelemetry.io/docs/collector/internal-telemetry/)
- [Collector resiliency](https://opentelemetry.io/docs/collector/resiliency/)
- [File storage extension](https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/main/extension/storage/filestorage)

**Next**: [Part 3: Kubernetes Installation](03_kubernetes_installation.md)
