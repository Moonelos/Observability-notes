"""Local console mode by default; explicit live Langfuse mode requires credentials."""
import os
import uuid
from langfuse import Langfuse
from opentelemetry import metrics, trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import ConsoleMetricExporter, PeriodicExportingMetricReader
from privacy import safe_text

resource = Resource.create({'service.name': os.getenv('OTEL_SERVICE_NAME', 'rag-service'),
                            'service.instance.id': str(uuid.uuid4()), 'service.version': 'local-lab',
                            'deployment.environment.name': 'development'})
provider = TracerProvider(resource=resource)
trace.set_tracer_provider(provider)
if os.getenv('LAB_LANGFUSE_LIVE') == '1':
    for field in ('LANGFUSE_PUBLIC_KEY', 'LANGFUSE_SECRET_KEY', 'LANGFUSE_BASE_URL'):
        if not os.getenv(field):
            raise RuntimeError(f'{field} required for live mode')
    langfuse = Langfuse(tracer_provider=provider, environment='development', release='local-lab',
                       mask=lambda **kwargs: safe_text(str(kwargs['data'])),
                       should_export_span=lambda span: True)
else:
    # Real Langfuse observation helpers, actual OTel SDK, local export. Scores below
    # use a local sink; console spans do not certify Langfuse backend ingestion.
    langfuse = Langfuse(public_key='pk-lf-local-lab', secret_key='local-not-a-real-key',
                       tracer_provider=provider, span_exporter=ConsoleSpanExporter(),
                       environment='development', release='local-lab', should_export_span=lambda span: True)
reader = PeriodicExportingMetricReader(ConsoleMetricExporter(), export_interval_millis=60000)
meter_provider = MeterProvider(resource=resource, metric_readers=[reader])
metrics.set_meter_provider(meter_provider)
scores: dict[str, dict] = {}

def create_score(**kwargs):
    if os.getenv('LAB_LANGFUSE_LIVE') == '1':
        langfuse.create_score(**kwargs)
    else:
        scores[kwargs['score_id']] = kwargs

def shutdown_observability():
    langfuse.flush()
    meter_provider.force_flush()
    meter_provider.shutdown()
    langfuse.shutdown()
