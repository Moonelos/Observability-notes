"""Complete console-first FastAPI baseline. Launch from this directory."""
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI
from pydantic import BaseModel, Field
from opentelemetry import trace, metrics
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor, BatchSpanProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import ConsoleMetricExporter, PeriodicExportingMetricReader
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

resource = Resource.create({'service.name': 'chat-api', 'service.instance.id': str(uuid.uuid4()),
                            'deployment.environment.name': 'development', 'service.version': 'local-lab'})
provider = TracerProvider(resource=resource)
if os.getenv('LAB_OTLP_ENDPOINT'):
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=os.environ['LAB_OTLP_ENDPOINT'])))
else:
    provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
trace.set_tracer_provider(provider)
reader = PeriodicExportingMetricReader(ConsoleMetricExporter(), export_interval_millis=60000)
meter_provider = MeterProvider(resource=resource, metric_readers=[reader])
metrics.set_meter_provider(meter_provider)
tracer = trace.get_tracer('lab.chat')
meter = metrics.get_meter('lab.chat')
requests = meter.create_counter('app.chat.requests', unit='{request}')
duration = meter.create_histogram('app.chat.duration', unit='s')
logging.basicConfig(level=logging.INFO, format='%(message)s')

@asynccontextmanager
async def lifespan(app):
    try:
        yield
    finally:
        meter_provider.force_flush()
        provider.shutdown()
        meter_provider.shutdown()

app = FastAPI(lifespan=lifespan)
FastAPIInstrumentor.instrument_app(app, tracer_provider=provider, meter_provider=meter_provider)

class Chat(BaseModel):
    question: str = Field(min_length=1, max_length=4000)

@app.post('/chat')
def chat(body: Chat):
    started = time.perf_counter()
    with tracer.start_as_current_span('rag.retrieve', record_exception=False) as span:
        span.set_attribute('rag.documents.returned', 1)
        # Product content is returned to the caller, never attached to telemetry.
        answer = 'Workspace admins reset SSO in Security settings. [doc_001]'
    current = trace.get_current_span().get_span_context()
    attrs = {'http.route': '/chat', 'app.outcome': 'success'}
    requests.add(1, attrs)
    duration.record(time.perf_counter() - started, attrs)
    logging.info('retrieved=1 trace_id=%032x span_id=%016x', current.trace_id, current.span_id)
    return {'answer': answer, 'trace_id': f'{current.trace_id:032x}'}
