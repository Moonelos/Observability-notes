"""Run from repo root: python examples/local/otel_genai_test.py."""
from contextlib import closing
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.trace import StatusCode
from otel_genai import Measurements, stream_attempt, agent_run


class Stream:
    def __init__(self, chunks, error=None):
        self.chunks = chunks
        self.error = error
        self.closed = False
    def __iter__(self):
        yield from self.chunks
        if self.error:
            raise self.error
    def close(self):
        self.closed = True


class Client:
    def __init__(self, stream):
        self.stream = stream
        self.requests = 0
    def create(self, **kwargs):
        self.requests += 1
        return self.stream


reader = InMemoryMetricReader()
mp = MeterProvider(metric_readers=[reader])
tp = TracerProvider()
exported = InMemorySpanExporter()
tp.add_span_processor(SimpleSpanProcessor(exported))
tracer = tp.get_tracer('fixture')
measured = Measurements(mp.get_meter('fixture'))

# First metadata arrives at 0.1, text at 0.4, usage at 0.5, finish at 0.6.
clock = iter([0, .1, .4, .5, .6]).__next__
stream = Stream([{'model': 'fixture-v1'}, {'text': 'CANARY_SECRET'},
                 {'usage': {'input': 10, 'output': 2}}])
client = Client(stream)
with agent_run(measured) as state:
    state['steps'] = 2
    state['tool_calls'] = 1
    assert list(stream_attempt(client, tracer, measured, clock=clock)) == ['CANARY_SECRET']
assert client.requests == 1 and stream.closed
span = exported.get_finished_spans()[0]
assert span.attributes['gen_ai.response.time_to_first_chunk'] == .1
assert span.attributes['app.llm.stream.chunk_count'] == 3
assert 'CANARY_SECRET' not in str(span.attributes) and not span.events
assert span.attributes['gen_ai.usage.input_tokens'] == 10

# Consumer cancellation must call close; no final usage means unknown, not zero.
stream2 = Stream([{'text': 'partial'}, {'usage': {'input': 5, 'output': 1}}])
with closing(stream_attempt(Client(stream2), tracer, measured)) as gen:
    assert next(gen) == 'partial'
assert stream2.closed
assert exported.get_finished_spans()[1].attributes['app.outcome'] == 'cancelled'

# Provider error still closes and ends the failed physical attempt.
stream3 = Stream([], RuntimeError('CANARY_SECRET'))
try:
    list(stream_attempt(Client(stream3), tracer, measured))
except RuntimeError:
    pass
else:
    raise AssertionError('expected provider failure')
assert stream3.closed
assert exported.get_finished_spans()[2].status.status_code == StatusCode.ERROR
assert all('CANARY_SECRET' not in str(s.attributes) and not s.events
           for s in exported.get_finished_spans())

# Retry is another physical attempt, never a second wrapper around the same call.
stream4 = Stream([{'usage': {'input': 3, 'output': 1}}])
client4 = Client(stream4)
list(stream_attempt(client4, tracer, measured))
assert client4.requests == 1 and len(exported.get_finished_spans()) == 4
metrics = {m.name: m for r in reader.get_metrics_data().resource_metrics
           for sc in r.scope_metrics for m in sc.metrics}
assert sum(p.value for p in metrics['llm.requests'].data.data_points) == 4
assert sum(p.value for p in metrics['llm.tokens'].data.data_points) == 16
assert sum(p.value for p in metrics['app.llm.usage_missing'].data.data_points) == 2
assert sum(p.count for p in metrics['llm.request.duration'].data.data_points) == 4
assert all(p.attributes['http.route'] == '/chat' for p in metrics['llm.tokens'].data.data_points)
assert metrics['agent.steps'].data.data_points[0].sum == 2
assert metrics['agent.tool.calls'].data.data_points[0].value == 1
assert metrics['app.llm.time_to_first_text'].data.data_points[0].sum >= .4
mp.shutdown(); tp.shutdown()
print('PASS physical attempts, metadata/text clocks, cancellation, failure cleanup, privacy, usage and agent metrics')
