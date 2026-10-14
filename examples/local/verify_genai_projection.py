"""Exercise the documented 0.159.0 filter with real OTLP and local file exports.

Run: python examples/local/verify_genai_projection.py /path/to/otelcol-contrib
Requires the chapter 02 Langfuse environment and an OTLP HTTP trace exporter.
"""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time

from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor


def read_spans(path):
    spans = []
    for line in path.read_text().splitlines():
        for resource in json.loads(line).get("resourceSpans", []):
            for scope in resource.get("scopeSpans", []):
                spans.extend(scope["spans"])
    return spans


def main():
    binary = str(Path(sys.argv[1]).resolve())
    assert "0.159.0" in subprocess.check_output([binary, "--version"], text=True)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    with tempfile.TemporaryDirectory(prefix="genai-projection-") as directory:
        folder = Path(directory)
        apm_path, genai_path = folder / "apm.json", folder / "genai.json"
        config = folder / "collector.yaml"
        config.write_text(f"""
receivers:
  otlp:
    protocols:
      http:
        endpoint: 127.0.0.1:{port}
processors:
  filter/genai_projection:
    error_mode: ignore
    trace_conditions:
      - 'span.attributes["app.telemetry.category"] != "genai"'
exporters:
  file/apm:
    path: {apm_path}
  file/genai:
    path: {genai_path}
service:
  telemetry:
    metrics:
      level: none
  pipelines:
    traces/apm:
      receivers: [otlp]
      exporters: [file/apm]
    traces/genai:
      receivers: [otlp]
      processors: [filter/genai_projection]
      exporters: [file/genai]
""")
        subprocess.run([binary, "validate", "--config", str(config)], check=True)
        with (folder / "collector.log").open("w") as output:
            process = subprocess.Popen(
                [binary, "--config", str(config)], stdout=output, stderr=output,
                env=os.environ.copy(),
            )
            provider = TracerProvider()
            try:
                for _ in range(100):
                    if process.poll() is not None:
                        raise RuntimeError((folder / "collector.log").read_text())
                    try:
                        with socket.create_connection(("127.0.0.1", port), timeout=.1):
                            break
                    except OSError:
                        time.sleep(.05)
                else:
                    raise TimeoutError("Collector receiver not ready")
                provider.add_span_processor(SimpleSpanProcessor(OTLPSpanExporter(
                    endpoint=f"http://127.0.0.1:{port}/v1/traces"
                )))
                tracer = provider.get_tracer("projection-canary")
                marked = {"app.telemetry.category": "genai"}
                with tracer.start_as_current_span("POST /chat", attributes=marked):
                    with tracer.start_as_current_span("load documents"):
                        pass
                    with tracer.start_as_current_span("answer question", attributes=marked):
                        with tracer.start_as_current_span("chat demo-model", attributes=marked):
                            pass
                    with tracer.start_as_current_span("persist answer"):
                        pass
                with tracer.start_as_current_span("GET /health"):
                    pass
            finally:
                provider.shutdown()
                process.terminate()
                process.wait(timeout=15)
        full, view = read_spans(apm_path), read_spans(genai_path)
        assert len(full) == 6 and len(view) == 3
        assert {s["name"] for s in view} == {
            "POST /chat", "answer question", "chat demo-model"
        }
        original = {s["spanId"]: s for s in full}
        ids = {s["spanId"] for s in view}
        assert len({s["traceId"] for s in view}) == 1
        assert sum(not s.get("parentSpanId") for s in view) == 1
        for span in view:
            assert not span.get("parentSpanId") or span["parentSpanId"] in ids
            assert span == original[span["spanId"]]
        print("PASS Collector 0.159.0: APM=6, GenAI=3; full parent chain and original span fields preserved")


if __name__ == "__main__":
    main()
