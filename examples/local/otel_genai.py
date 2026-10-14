"""Provider-neutral physical attempt wrapper; no network or global provider setup.
Fake chunks use {text, model, usage:{input,output}}. Real adapters must normalize
provider responses into this shape and disable hidden client retries.
"""
import time
from contextlib import contextmanager
from opentelemetry.trace import SpanKind, Status, StatusCode


class Measurements:
    def __init__(self, meter):
        self.requests = meter.create_counter('llm.requests', unit='{request}')
        self.duration = meter.create_histogram('llm.request.duration', unit='s')
        self.tokens = meter.create_counter('llm.tokens', unit='{token}')
        self.first_chunk = meter.create_histogram('app.llm.time_to_first_chunk', unit='s')
        self.first_text = meter.create_histogram('app.llm.time_to_first_text', unit='s')
        self.usage_missing = meter.create_counter('app.llm.usage_missing', unit='{request}')
        self.agent_steps = meter.create_histogram('agent.steps', unit='{step}')
        self.agent_tools = meter.create_counter('agent.tool.calls', unit='{call}')

    def finish(self, attrs, elapsed, usage):
        self.requests.add(1, attrs)
        self.duration.record(elapsed, attrs)
        if usage is None:
            self.usage_missing.add(1, attrs)
        else:
            for direction in ('input', 'output'):
                self.tokens.add(usage[direction], {**attrs, 'gen_ai.token.type': direction})


def stream_attempt(client, tracer, measured, *, model='fixture-model', route='/chat',
                   clock=time.perf_counter):
    """Caller must explicitly close on cancellation (use contextlib.closing).
    Span is created without leaving active Context attached across yielded text.
    Content is forwarded, never concatenated into a telemetry buffer.
    """
    attrs = {'gen_ai.operation.name': 'chat', 'gen_ai.provider.name': 'fixture',
             'gen_ai.request.model': model, 'http.route': route}
    start = clock()
    span = tracer.start_span(f'chat {model}', kind=SpanKind.CLIENT,
                             attributes={**attrs, 'gen_ai.request.stream': True})
    stream = None
    usage = None
    first = None
    first_text = None
    count = 0
    outcome = 'error'
    try:
        # Exactly one request. A logical retry calls this wrapper again.
        stream = client.create(model=model, stream=True)
        for chunk in stream:
            now = clock()
            count += 1
            if first is None:
                first = now - start
                span.set_attribute('gen_ai.response.time_to_first_chunk', first)
                measured.first_chunk.record(first, attrs)
            if chunk.get('model'):
                span.set_attribute('gen_ai.response.model', chunk['model'])
            if chunk.get('usage') is not None:
                usage = chunk['usage']
                span.set_attribute('gen_ai.usage.input_tokens', usage['input'])
                span.set_attribute('gen_ai.usage.output_tokens', usage['output'])
            text = chunk.get('text', '')
            if text:
                if first_text is None:
                    first_text = now - start
                    measured.first_text.record(first_text, attrs)
                yield text
        outcome = 'success'
    except GeneratorExit:
        outcome = 'cancelled'
        raise
    except Exception as exc:
        span.set_attribute('error.type', type(exc).__name__)
        span.set_status(Status(StatusCode.ERROR))
        raise
    finally:
        try:
            if stream is not None:
                stream.close()
        except Exception as exc:
            outcome = 'error'
            span.set_attribute('error.type', type(exc).__name__)
            span.set_status(Status(StatusCode.ERROR))
            raise
        finally:
            span.set_attribute('app.outcome', outcome)
            span.set_attribute('app.llm.stream.chunk_count', count)
            measured.finish({**attrs, 'app.outcome': outcome}, clock() - start, usage)
            span.end()


@contextmanager
def agent_run(measured):
    """Application-owned counts; caller increments at each real step/tool call."""
    state = {'steps': 0, 'tool_calls': 0, 'outcome': 'success'}
    try:
        yield state
    except BaseException:
        state['outcome'] = 'error'
        raise
    finally:
        attrs = {'agent.name': 'support', 'http.route': '/chat', 'app.outcome': state['outcome']}
        measured.agent_steps.record(state['steps'], attrs)
        measured.agent_tools.add(state['tool_calls'], attrs)
