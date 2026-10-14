import os
from uuid import uuid4
from contextlib import asynccontextmanager
import httpx
from fastapi import FastAPI, Depends, HTTPException
from pydantic import BaseModel, Field
from opentelemetry import baggage, context, trace
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from identity import Identity, require_identity
from observability import langfuse, shutdown_observability
from privacy import safe_text

HTTPXClientInstrumentor().instrument()
@asynccontextmanager
async def lifespan(app):
    token = os.environ.get('INTERNAL_AGENT_TOKEN')
    if not token:
        raise RuntimeError('INTERNAL_AGENT_TOKEN required')
    app.state.client = httpx.AsyncClient(timeout=5, headers={'authorization': 'Bearer ' + token})
    try: yield
    finally:
        await app.state.client.aclose()
        shutdown_observability()

app = FastAPI(lifespan=lifespan)
FastAPIInstrumentor.instrument_app(app)
class Question(BaseModel):
    question: str = Field(min_length=1, max_length=4000)

@app.post('/answer')
@app.post('/chat')
async def answer(body: Question, identity: Identity = Depends(require_identity)):
    # Discard all externally supplied baggage while preserving trace context.
    trusted = baggage.clear()
    trusted = baggage.set_baggage('app.tenant.tier', 'enterprise', context=trusted)
    handle = context.attach(trusted)
    trace.get_current_span().set_attribute('app.tenant.tier', 'enterprise')
    try:
        with langfuse.start_as_current_observation(as_type='span', name='gateway.answer', input={'question': safe_text(body.question)}):
            trace_id = langfuse.get_current_trace_id()
            docs = []
            if os.getenv('RETRIEVAL_SERVICE_URL'):
                response = await app.state.client.post(os.environ['RETRIEVAL_SERVICE_URL'] + '/search')
                response.raise_for_status()
                docs = response.json()['document_ids']
            payload = {'request_id': str(uuid4()), 'question': body.question, 'document_ids': docs}
            result = None
            for attempt in range(2):
                try:
                    response = await app.state.client.post(os.getenv('AGENT_SERVICE_URL', 'http://127.0.0.1:8081') + '/run', json=payload)
                    response.raise_for_status()
                    result = response.json()
                    break
                except (httpx.TimeoutException, httpx.ConnectError):
                    if attempt: raise HTTPException(504, 'agent unavailable')
                except httpx.HTTPStatusError as exc:
                    raise HTTPException(502, 'agent request rejected') from exc
            return result | {'langfuse_trace_id': trace_id}
    finally:
        context.detach(handle)
