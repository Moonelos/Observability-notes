"""Real pinned Langfuse SDK; deterministic provider and local-only exporter."""
import argparse
import json
import os

from langfuse import Langfuse, propagate_attributes
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--remote', action='store_true')
    args = parser.parse_args()
    memory = InMemorySpanExporter()
    if args.remote:
        for key in ('LANGFUSE_PUBLIC_KEY', 'LANGFUSE_SECRET_KEY', 'LANGFUSE_BASE_URL'):
            if not os.environ.get(key):
                raise RuntimeError(f'{key} required for remote mode')
        lf = Langfuse()
    else:
        # Dummy keys identify this local client. No auth check or API write occurs.
        lf = Langfuse(public_key='pk-lf-local-smoke', secret_key='sk-lf-local-smoke',
                      base_url='http://127.0.0.1:1', tracer_provider=TracerProvider(),
                      span_exporter=memory, flush_interval=3600,
                      environment='local', release='sso-a1')
    question = 'How do I reset SSO?'
    trace_id = generation_id = None
    try:
        with propagate_attributes(user_id='user_demo_42', session_id='session_demo_7',
                                  trace_name='rag.answer', version='prompt-v17',
                                  metadata={'feature': 'support', 'tenantTier': 'enterprise'}):
            with lf.start_as_current_observation(name='rag.answer', as_type='span',
                                                input={'question': question}) as root:
                trace_id = lf.get_current_trace_id()
                with lf.start_as_current_observation(name='rag.retrieve', as_type='retriever',
                                                    input={'query': question}) as retrieval:
                    doc = {'id': 'doc_001', 'revision': 'r3',
                           'approved_excerpt': 'Reset SSO in Settings > Security.'}
                    retrieval.update(output={'documents': [doc]})
                messages = [{'role': 'user', 'content': question + '\n' + doc['approved_excerpt']}]
                with lf.start_as_current_observation(name='llm.generate_answer', as_type='generation',
                                                    model='local-stub', input=messages) as generation:
                    generation_id = lf.get_current_observation_id()
                    answer = 'Open Settings > Security to reset SSO. [doc_001]'
                    generation.update(output=answer, usage_details={'input': 820, 'output': 164})
                root.update(output={'answer': answer})
        print(json.dumps({'answer': answer, 'trace_id': trace_id, 'generation_id': generation_id}))
    finally:
        # Ending a context queues spans; flushing explicitly exports the final batch.
        lf.flush()
        if not args.remote:
            spans = memory.get_finished_spans()
            by_name = {span.name: span for span in spans}
            assert set(by_name) == {'rag.answer', 'rag.retrieve', 'llm.generate_answer'}
            root_span = by_name['rag.answer']
            for name in ('rag.retrieve', 'llm.generate_answer'):
                assert by_name[name].parent.span_id == root_span.context.span_id
                assert by_name[name].context.trace_id == root_span.context.trace_id
            assert f'{root_span.context.trace_id:032x}' == trace_id
            print('PASS: 3 observations; one trace; both children parented to rag.answer; final batch flushed')
        lf.shutdown()


if __name__ == '__main__':
    main()
