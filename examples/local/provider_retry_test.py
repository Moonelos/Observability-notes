"""Run the documented provider continuations against a local SDK transport.

Requires the examples/README.md dependency environment. No network traffic is sent.
"""
import os
import re
import sys
import types
from pathlib import Path

import httpx
from langfuse import Langfuse
from openai import OpenAI
from opentelemetry import metrics
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

ROOT = Path(__file__).resolve().parents[2]
os.environ["OPENAI_API_KEY"] = "local-fixture-not-a-credential"
os.environ["LANGFUSE_TRACING_ENVIRONMENT"] = "development"
reader = InMemoryMetricReader()
metrics.set_meter_provider(MeterProvider(metric_readers=[reader]))
exporter = InMemorySpanExporter()
lf = Langfuse(
    public_key="pk-lf-local", secret_key="local-fixture",
    tracer_provider=TracerProvider(), span_exporter=exporter,
)
# The RAG excerpt's citation evaluator writes a score: make that an explicit local fixture.
lf.score_current_trace = lambda **kwargs: None
observability = types.ModuleType("observability")
observability.langfuse = lf
observability.shutdown_observability = lambda: None
sys.modules["observability"] = observability


def load_excerpt(filename, marker):
    blocks = re.findall(r"```python\n(.*?)```", (ROOT / "examples" / filename).read_text(), re.S)
    source = next(block for block in blocks if block.startswith(marker))
    module = types.ModuleType("checked_" + filename[:2])
    sys.modules[module.__name__] = module
    exec(compile(source, filename, "exec"), module.__dict__)
    assert module.openai.max_retries == 0
    assert module.openai.timeout == 1.0
    module.openai.close()
    return module


def check(module, generation_name, invoke):
    calls = []

    def transport(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(500, json={"error": {"message": "synthetic-secret-canary", "type": "server_error"}})
        return httpx.Response(200, json={
            "id": "fixture-completion", "object": "chat.completion", "created": 0,
            "model": "gpt-4o-mini", "choices": [{"index": 0, "message": {
                "role": "assistant", "content": "Reset SSO [doc_001]"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        })

    module.openai = OpenAI(
        api_key="local-fixture", base_url="http://unused.local/v1", max_retries=0,
        timeout=1.0, http_client=httpx.Client(transport=httpx.MockTransport(transport)),
    )
    exporter.clear()
    try:
        invoke(module)
        lf.flush()
        generations = [s for s in exporter.get_finished_spans() if s.name == generation_name]
        assert len(calls) == len(generations) == 2, (len(calls), len(generations))
        failed, succeeded = generations
        exported_payloads = [
            (dict(span.attributes), span.status.description,
             [(event.name, dict(event.attributes or {})) for event in span.events])
            for span in exporter.get_finished_spans()
        ]
        assert "synthetic-secret-canary" not in repr(exported_payloads)
        assert failed.parent.span_id == succeeded.parent.span_id
        assert failed.status.status_code == StatusCode.ERROR
        assert failed.attributes.get("langfuse.observation.level") == "ERROR"
        assert succeeded.status.status_code != StatusCode.ERROR
        assert "langfuse.observation.usage_details" not in failed.attributes
        assert '"input_tokens": 10' in succeeded.attributes["langfuse.observation.usage_details"]
        data = reader.get_metrics_data()
        scope_metrics = [sm for rm in data.resource_metrics for sm in rm.scope_metrics
                         if sm.scope.name == module.meter.name]
        by_name = {m.name: m for sm in scope_metrics for m in sm.metrics}
        duration = by_name["gen_ai.client.operation.duration"].data.data_points
        assert {p.attributes["app.outcome"]: p.count for p in duration} == {"error": 1, "success": 1}
        failures = by_name["gen_ai.client.operation.failures"].data.data_points
        assert sum(p.value for p in failures) == 1
        tokens = by_name["gen_ai.client.token.usage"].data.data_points
        assert sum(p.count for p in tokens) == 2
        assert sum(p.sum for p in tokens) == 15
        print(f"PASS {generation_name}: HTTP attempts=2; generations=2; ERROR then success; "
              "durations=2; failures=1; failed usage unknown; known tokens=15")
    finally:
        module.openai.close()


try:
    rag = load_excerpt("01_rag_with_otel_and_langfuse.md", "import os")
    check(rag, "llm.generate_answer", lambda m: m.answer_question(
        "How do I reset SSO?", user_id="user-a", session_id="session-a"))
    agent = load_excerpt("02_multi_service_agent.md", "# agent_service.py")
    check(agent, "llm.decide", lambda m: m.execute_agent(m.RunRequest(
        request_id="request-0001", question="How do I reset SSO?", account_id="account-a")))
finally:
    lf.shutdown()
    metrics.get_meter_provider().shutdown()
