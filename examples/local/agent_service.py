import time
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, HTTPException
from pydantic import BaseModel, Field
from opentelemetry import metrics
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from identity import Identity, require_gateway, ACCOUNTS
from observability import langfuse, shutdown_observability
from privacy import safe_text
from result_store import ResultStore

store = ResultStore()
meter = metrics.get_meter('example.agent')
steps_hist = meter.create_histogram('agent.steps', unit='{step}')
tool_calls = meter.create_counter('agent.tool.calls', unit='{call}')
duration = meter.create_histogram('gen_ai.client.operation.duration', unit='s')
tokens = meter.create_histogram('gen_ai.client.token.usage', unit='{token}')

@asynccontextmanager
async def lifespan(app):
    try: yield
    finally: shutdown_observability()

app = FastAPI(lifespan=lifespan)
FastAPIInstrumentor.instrument_app(app)
class RunRequest(BaseModel):
    request_id: str = Field(min_length=8, max_length=128)
    question: str = Field(min_length=1, max_length=4000)
    # Payload binding includes approved retrieval identity, never raw document data.
    document_ids: list[str] = Field(default_factory=list, max_length=5)

@app.post('/run')
def run_agent(body: RunRequest, identity: Identity = Depends(require_gateway)):
    def execute():
        with langfuse.start_as_current_observation(as_type='agent', name='agent.answer', input={'question': safe_text(body.question)}) as agent:
            attrs = {'http.route': '/run', 'gen_ai.operation.name': 'chat', 'gen_ai.provider.name': 'local', 'gen_ai.request.model': 'stub'}
            # Fake model makes two decisions: read account, then answer. Its fixed
            # decision fixtures isolate loop mechanics from model nondeterminism.
            for step in (1, 2):
                started = time.perf_counter()
                with langfuse.start_as_current_observation(as_type='generation', name='llm.decide', model='stub') as generation:
                    generation.update(output={'decision': 'lookup_account' if step == 1 else 'final_answer'},
                                      usage_details={'input_tokens': 100, 'output_tokens': 20})
                duration.record(time.perf_counter() - started, attrs | {'app.outcome': 'success'})
                tokens.record(100, attrs | {'gen_ai.token.type': 'input'})
                tokens.record(20, attrs | {'gen_ai.token.type': 'output'})
                if step == 1:
                    with langfuse.start_as_current_observation(as_type='tool', name='tool.lookup_account') as tool:
                        account = ACCOUNTS[identity.account_id]
                        tool.update(output=account)
                    tool_calls.add(1, {'tool.name': 'lookup_account', 'app.outcome': 'success', 'http.route': '/run'})
            steps_hist.record(2, {'http.route': '/run', 'app.outcome': 'success'})
            result = {'answer': 'Workspace admins reset SSO in Security settings. [doc_001]',
                      'steps': 2, 'stop_reason': 'final_answer', 'tier': account['tier']}
            agent.update(output={'steps': 2, 'stop_reason': 'final_answer'})
            return result
    # Tenant is part of the dedup key. Sensitive identity comes from the verifier.
    return store.run((identity.tenant_id, body.request_id), body.model_dump(), execute)
