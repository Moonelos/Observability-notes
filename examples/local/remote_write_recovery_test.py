"""Test the documented remote-write exporter against an isolated 503 outage.

Uses Python's standard library, an exact Collector binary, and one OTLP/JSON
point. The backend compares compressed request bytes; no external traffic occurs.
"""
from __future__ import annotations

import argparse
import http.server
import json
from pathlib import Path
import re
import socket
import subprocess
import tempfile
import threading
import time
import urllib.request
import uuid


def free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("collector", type=Path)
    parser.add_argument("--expected-version", default="0.158.0",
                        help="exact reviewed candidate version (default: 0.158.0)")
    parser.add_argument("--default-timeout", action="store_true",
                        help="reproduce the historical five-second loss")
    args = parser.parse_args()
    binary = str(args.collector.resolve())
    version = subprocess.check_output([binary, "--version"], text=True)
    if not re.fullmatch(r"0\.\d+\.\d+", args.expected_version):
        parser.error("expected-version must be an exact 0.x.y version")
    if not re.search(r"\b" + re.escape(args.expected_version) + r"\b", version):
        raise SystemExit(f"Requires Contrib {args.expected_version}; got {version.strip()}")
    if args.default_timeout and args.expected_version != "0.158.0":
        parser.error("default-timeout loss reproduction is specific to 0.158.0")

    root = Path(__file__).resolve().parents[2]
    note = (root / "examples/03_collector_prometheus_langfuse.md").read_text()
    config_fence = re.search(r"```yaml\n(.*?)```", note, re.S).group(1)
    # Extract the actual documented exporter rather than maintaining a test copy.
    exporter = config_fence.split("  prometheus_remote_write:\n", 1)[1]
    exporter = exporter.split("\n  otlp/logs:", 1)[0]
    first_attempt = threading.Event()
    recovered = threading.Event()
    lock = threading.Lock()
    attempts: list[bytes] = []
    receipts: list[bytes] = []

    class Backend(http.server.BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            with lock:
                attempts.append(body)
                success = recovered.is_set()
                if success:
                    receipts.append(body)
                first_attempt.set()
            self.send_response(200 if success else 503)
            self.end_headers()

        def log_message(self, *_args) -> None:
            pass

    backend = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Backend)
    backend_thread = threading.Thread(target=backend.serve_forever, daemon=True)
    backend_thread.start()
    ingest_port = free_port()
    exporter = exporter.replace("https://prometheus.example.com/api/v1/write",
                                f"http://127.0.0.1:{backend.server_port}/api/v1/write")
    if args.default_timeout:
        exporter = exporter.replace("    timeout: 10m\n", "")

    try:
        with tempfile.TemporaryDirectory(prefix="remote-write-recovery-") as tmp:
            folder = Path(tmp)
            config = folder / "collector.yaml"
            config.write_text(f"""receivers:
  otlp:
    protocols:
      http:
        endpoint: 127.0.0.1:{ingest_port}
exporters:
  prometheus_remote_write:
{exporter}
service:
  telemetry:
    metrics:
      level: none
  pipelines:
    metrics:
      receivers: [otlp]
      exporters: [prometheus_remote_write]
""")
            subprocess.run([binary, "validate", "--config", str(config)], check=True)
            log_path = folder / "collector.log"
            with log_path.open("w") as log:
                process = subprocess.Popen([binary, "--config", str(config)],
                                           stdout=log, stderr=log)
                try:
                    deadline = time.monotonic() + 10
                    while True:
                        if process.poll() is not None:
                            raise AssertionError(log_path.read_text())
                        try:
                            with socket.create_connection(("127.0.0.1", ingest_port),
                                                          timeout=0.1):
                                break
                        except OSError:
                            if time.monotonic() >= deadline:
                                raise TimeoutError("Collector never opened OTLP")
                            time.sleep(0.05)
                    now = time.time_ns()
                    metric_name = "recovery.requests." + uuid.uuid4().hex
                    point = {"resourceMetrics": [{"resource": {"attributes": [
                        {"key": "service.name", "value": {"stringValue": "local-recovery"}}
                    ]}, "scopeMetrics": [{"scope": {"name": "recovery-test"}, "metrics": [{
                        "name": metric_name, "unit": "{request}", "sum": {
                            "aggregationTemporality": 2, "isMonotonic": True,
                            "dataPoints": [{"asInt": "1", "timeUnixNano": str(now),
                                            "startTimeUnixNano": str(now - 1_000_000_000)}]
                        }
                    }]}]}]}
                    request = urllib.request.Request(
                        f"http://127.0.0.1:{ingest_port}/v1/metrics",
                        json.dumps(point).encode(), {"Content-Type": "application/json"})
                    # This is the only OTLP emission. Recovery cannot be a new canary.
                    with urllib.request.urlopen(request, timeout=3) as response:
                        assert response.status == 200
                    assert first_attempt.wait(5), "backend received no export"
                    time.sleep(8)
                    recovered.set()
                    deadline = time.monotonic() + 12
                    while time.monotonic() < deadline:
                        with lock:
                            if receipts:
                                break
                        if args.default_timeout:
                            if "context deadline exceeded" in log_path.read_text():
                                break
                        time.sleep(0.1)
                finally:
                    process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
            logs = log_path.read_text()
            if args.default_timeout:
                assert attempts and not receipts, (len(attempts), len(receipts))
                assert "context deadline exceeded" in logs, logs
                print("PASS reproduced default-timeout loss: 8s outage, zero receipts, deadline exceeded")
            else:
                assert receipts, logs
                assert receipts[0] == attempts[0], "recovery payload differs from original"
                print("PASS original remote-write payload recovered after 8s outage")
                print(f"OTLP emissions=1; backend attempts={len(attempts)}; receipts={len(receipts)}")
    finally:
        backend.shutdown()
        backend.server_close()
        backend_thread.join(timeout=2)


if __name__ == "__main__":
    main()
