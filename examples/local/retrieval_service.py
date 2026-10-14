from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends
from opentelemetry import trace, baggage
from opentelemetry.sdk.trace import SpanProcessor
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from identity import require_gateway
from observability import provider, shutdown_observability
import os

class TierProcessor(SpanProcessor):
    def on_start(self, span, parent_context=None):
        tier = baggage.get_baggage('app.tenant.tier', context=parent_context)
        if tier in {'enterprise', 'standard'}:
            span.set_attribute('app.tenant.tier', tier)
    def on_end(self, span): pass
    def shutdown(self): pass
    def force_flush(self, timeout_millis=30000): return True

if os.getenv('LAB_DISABLE_TIER') != '1':
    provider.add_span_processor(TierProcessor())
tracer = trace.get_tracer('lab.retrieval')
@asynccontextmanager
async def lifespan(app):
    try: yield
    finally: shutdown_observability()
app = FastAPI(lifespan=lifespan)
FastAPIInstrumentor.instrument_app(app)
@app.post('/search', dependencies=[Depends(require_gateway)])
def search():
    with tracer.start_as_current_span('vector_db.query', record_exception=False):
        return {'document_ids': ['doc_001']}
