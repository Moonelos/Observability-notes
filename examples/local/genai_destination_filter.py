"""Local destination filtering canary; no credentials, Collector, or network.

Run with the Langfuse 4.17.0 environment from langfuse/02_python_sdk_v4.md.
"""
from collections.abc import Sequence

from langfuse import Langfuse
from opentelemetry._logs import SeverityNumber
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import (
    InMemoryLogRecordExporter,
    SimpleLogRecordProcessor,
)
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    SpanExporter,
    SpanExportResult,
)
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter


def keep_genai_view(span: ReadableSpan) -> bool:
    return (span.attributes or {}).get("app.telemetry.category") == "genai"


class GenAIViewExporter(SpanExporter):
    """Wrap only the GenAI destination's exporter; never mutate shared spans."""

    def __init__(self, delegate: SpanExporter):
        self.delegate = delegate

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        selected = tuple(span for span in spans if keep_genai_view(span))
        return self.delegate.export(selected) if selected else SpanExportResult.SUCCESS

    def force_flush(self, timeout_millis: int = 30_000) -> bool:
        return self.delegate.force_flush(timeout_millis)

    def shutdown(self) -> None:
        self.delegate.shutdown()


def run(mode: str) -> None:
    provider = TracerProvider()
    apm = InMemorySpanExporter()
    genai = InMemorySpanExporter()
    provider.add_span_processor(BatchSpanProcessor(apm))
    client = None
    if mode == "raw-otel":
        provider.add_span_processor(BatchSpanProcessor(GenAIViewExporter(genai)))
    else:
        client = Langfuse(
            public_key="pk-lf-local-filter-canary",
            secret_key="sk-lf-local-filter-canary",
            tracer_provider=provider,
            span_exporter=genai,
            should_export_span=keep_genai_view,
        )
    log_exporter = InMemoryLogRecordExporter()
    logs = LoggerProvider()
    logs.add_log_record_processor(SimpleLogRecordProcessor(log_exporter))
    logger = logs.get_logger("filter-canary")
    tracer = provider.get_tracer("filter-canary")
    marker = {"app.telemetry.category": "genai"}
    try:
        with tracer.start_as_current_span("POST /chat", attributes=marker):
            with tracer.start_as_current_span("load documents"):
                pass
            with tracer.start_as_current_span("answer question", attributes=marker):
                with tracer.start_as_current_span(
                    "chat demo-model",
                    attributes=marker | {"gen_ai.operation.name": "chat"},
                ) as model:
                    logger.emit(
                        event_name="app.provider.retry.scheduled",
                        severity_number=SeverityNumber.INFO,
                        body="retry scheduled",
                        attributes={"app.retry.attempt": 2},
                    )
                    model_context = model.get_span_context()
                with tracer.start_as_current_span("persist answer"):
                    pass
        with tracer.start_as_current_span("GET /health"):
            pass
        assert provider.force_flush(timeout_millis=30_000)
        full = apm.get_finished_spans()
        selected = genai.get_finished_spans()
        assert len(full) == 6
        assert {s.name for s in selected} == {
            "POST /chat", "answer question", "chat demo-model"
        }
        ids = {s.context.span_id for s in selected}
        original = {s.context.span_id: s for s in full}
        assert len({s.context.trace_id for s in selected}) == 1
        assert sum(s.parent is None for s in selected) == 1
        for span in selected:
            assert span.parent is None or span.parent.span_id in ids
            source = original[span.context.span_id]
            assert (span.context, span.parent, span.start_time, span.end_time) == (
                source.context, source.parent, source.start_time, source.end_time
            )
            assert not span.events
        event, = log_exporter.get_finished_logs()
        assert event.log_record.event_name == "app.provider.retry.scheduled"
        assert event.log_record.trace_id == model_context.trace_id
        assert event.log_record.span_id == model_context.span_id
        # A model-only predicate would drop two required ancestors.
        leaves = [s for s in full if "gen_ai.operation.name" in s.attributes]
        assert len(leaves) == 1 and leaves[0].parent.span_id not in {
            s.context.span_id for s in leaves
        }
        print(f"PASS {mode}: APM=6, GenAI=3; ancestors and IDs preserved; named log correlated")
    finally:
        if client is not None:
            client.flush()
        provider.shutdown()
        logs.shutdown()


if __name__ == "__main__":
    run("raw-otel")
    run("langfuse-sdk")
