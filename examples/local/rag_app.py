"""Complete local RAG plus authorized late feedback; no provider calls."""
import threading
import time
from contextlib import asynccontextmanager
from uuid import uuid4, uuid5, NAMESPACE_URL
from fastapi import FastAPI, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from opentelemetry import metrics
from observability import langfuse, create_score, shutdown_observability
from identity import Identity, require_identity
from privacy import safe_text

meter = metrics.get_meter('example.rag')
retrieval_documents = meter.create_histogram('rag.retrieval.documents', unit='{document}')
empty_retrievals = meter.create_counter('rag.retrieval.empty', unit='{request}')
operation_duration = meter.create_histogram('gen_ai.client.operation.duration', unit='s')
token_usage = meter.create_histogram('gen_ai.client.token.usage', unit='{token}')
answers = {}
feedback = {}
lock = threading.Lock()

@asynccontextmanager
async def lifespan(app):
    try:
        yield
    finally:
        shutdown_observability()

app = FastAPI(lifespan=lifespan)
class Question(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
class Feedback(BaseModel):
    accepted: bool
    comment: str | None = Field(default=None, max_length=500)

@app.post('/answer')
def answer(body: Question, identity: Identity = Depends(require_identity)):
    with langfuse.start_as_current_observation(as_type='span', name='rag.answer', input={'question': safe_text(body.question)}) as root:
        trace_id = langfuse.get_current_trace_id()
        with langfuse.start_as_current_observation(as_type='retriever', name='rag.retrieve') as retrieval:
            documents = [] if body.question == 'EMPTY' else ['doc_001']
            retrieval_documents.record(len(documents), {'http.route': '/answer', 'retrieval.strategy': 'local'})
            retrieval.update(output={'document_ids': documents})
        if not documents:
            empty_retrievals.add(1, {'http.route': '/answer', 'retrieval.strategy': 'local'})
            result = {'status': 'no_context', 'answer': 'No approved sources.', 'citations_present': False}
        else:
            attrs = {'http.route': '/answer', 'gen_ai.operation.name': 'chat', 'gen_ai.provider.name': 'local', 'gen_ai.request.model': 'stub'}
            started = time.perf_counter()
            with langfuse.start_as_current_observation(as_type='generation', name='llm.generate_answer', model='stub', input={'content': '[CONTENT OMITTED]'}) as generation:
                text = 'Workspace admins reset SSO in Security settings. [doc_001]'
                generation.update(output=safe_text(text), usage_details={'input_tokens': 820, 'output_tokens': 164})
                token_usage.record(820, attrs | {'gen_ai.token.type': 'input'})
                token_usage.record(164, attrs | {'gen_ai.token.type': 'output'})
            operation_duration.record(time.perf_counter() - started, attrs | {'app.outcome': 'success'})
            with langfuse.start_as_current_observation(as_type='evaluator', name='evaluator.citation_check') as evaluator:
                evaluator.update(output={'citation_present': True})
                create_score(score_id=str(uuid4()), trace_id=trace_id, name='citation_present', value=1, data_type='BOOLEAN')
            result = {'status': 'answered', 'answer': text, 'citations_present': True}
        root.update(output={'status': result['status'], 'answer': safe_text(result['answer'])})
    result['langfuse_trace_id'] = trace_id
    with lock:
        answers[trace_id] = {'user_id': identity.user_id, 'tenant_id': identity.tenant_id, 'result': result}
    return result

@app.post('/answers/{trace_id}/feedback', status_code=204)
def record_feedback(trace_id: str, body: Feedback, identity: Identity = Depends(require_identity),
                    idempotency_key: str = Header(min_length=8, max_length=128)):
    with lock:
        stored = answers.get(trace_id)
        if not stored or stored['user_id'] != identity.user_id or stored['tenant_id'] != identity.tenant_id:
            raise HTTPException(404, 'answer not found')
        key = (trace_id, idempotency_key)
        payload = body.model_dump()
        if key in feedback:
            if feedback[key] != payload:
                raise HTTPException(409, 'idempotency payload conflict')
            return
        create_score(score_id=str(uuid5(NAMESPACE_URL, f'{trace_id}:user_accepted:{idempotency_key}')),
                     trace_id=trace_id, name='user_accepted', value=int(body.accepted), data_type='BOOLEAN',
                     comment=safe_text(body.comment or '', limit=500))
        feedback[key] = payload
