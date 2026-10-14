"""Run: python examples/local/otel_collector_test.py /path/to/otelcol-contrib
Isolates named policies without fallback; local files and sockets only.
Requires the Python 02 environment plus PyYAML and OTLP HTTP exporter.
"""
import copy
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path
import yaml
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.trace import Status, StatusCode, use_span

BASE = Path(__file__).parent
SOURCE = yaml.safe_load((BASE / 'otel_collector_routing.yaml').read_text())
BINARY = sys.argv[1]
assert '0.158.0' in subprocess.check_output([BINARY, '--version'], text=True)


def port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def wait_receiver(p, proc):
    for _ in range(100):
        if proc.poll() is not None:
            raise RuntimeError('Collector exited before receiver readiness')
        try:
            with socket.create_connection(('127.0.0.1', p), timeout=.1):
                return
        except OSError:
            time.sleep(.05)
    raise RuntimeError('receiver readiness timeout')


def emit(tracer, name, attrs, *, error=False, duration=.01, children=0):
    start = time.time_ns()
    root = tracer.start_span(name, attributes=attrs, start_time=start)
    with use_span(root, end_on_exit=False):
        for i in range(children):
            span = tracer.start_span(f'{name}-child-{i}')
            span.end()
    if error:
        root.set_status(Status(StatusCode.ERROR))
    root.end(end_time=start + int(duration * 1e9))


def retained_names(path):
    if not path.exists():
        return set()
    names = set()
    for line in path.read_text().splitlines():
        for rs in json.loads(line).get('resourceSpans', []):
            for ss in rs.get('scopeSpans', []):
                names.update(s['name'] for s in ss['spans'])
    return names


base = {'llm.workflow': True}
cases = {
 'keep-llm-errors': (base, {'error': True}, base, {}),
 'keep-provider-error-types': (base | {'error.type': 'TimeoutError'}, {}, base | {'error.type': 'OtherError'}, {}),
 'keep-slow-llm-traces': (base, {'duration': 16}, base, {'duration': 14}),
 'keep-large-agent-traces': (base, {'children': 39}, base, {'children': 38}),
 'keep-high-input-token-traces': (base | {'gen_ai.usage.input_tokens': 8000}, {}, base | {'gen_ai.usage.input_tokens': 7999}, {}),
 'keep-high-output-token-traces': (base | {'gen_ai.usage.output_tokens': 4096}, {}, base | {'gen_ai.usage.output_tokens': 4095}, {}),
 'keep-high-cost-traces': (base | {'app.llm.cost_microusd': 500000}, {}, base | {'app.llm.cost_microusd': 499999}, {}),
 'keep-guardrail-blocks': (base | {'app.guardrail.blocked': True}, {}, base | {'app.guardrail.blocked': False}, {}),
 'keep-selected-models': (base | {'gen_ai.request.model': 'gpt-4.1'}, {}, base | {'gen_ai.request.model': 'other'}, {}),
 'keep-selected-experiments': (base | {'app.experiment.name': 'rag-reranker-v2'}, {}, base | {'app.experiment.name': 'other'}, {}),
 'keep-selected-tenant-tiers': (base | {'app.tenant.tier': 'enterprise'}, {}, base | {'app.tenant.tier': 'free'}, {}),
 'keep-new-release-burn-in': (base | {'service.version': '2026.07.20-1'}, {}, base | {'service.version': 'other'}, {}),
}
policies = {p['name']: p for p in SOURCE['processors']['tail_sampling/langfuse']['policies']}
with tempfile.TemporaryDirectory(prefix='otel-policy-') as temp:
    td = Path(temp)
    for name, (positive, popts, negative, nopts) in cases.items():
        output = td / (name + '.json')
        http_port = port()
        sampler = copy.deepcopy(SOURCE['processors']['tail_sampling/langfuse'])
        sampler.update(decision_wait='300ms', num_traces=200)
        sampler['policies'] = [policies[name]]  # no probabilistic fallback
        conf = {
            'receivers': {'otlp': {'protocols': {'http': {'endpoint': f'127.0.0.1:{http_port}'}}}},
            'processors': {'tail_sampling': sampler},
            'exporters': {'file': {'path': str(output)}},
            'service': {'pipelines': {'traces': {'receivers': ['otlp'], 'processors': ['tail_sampling'], 'exporters': ['file']}}},
        }
        config = td / 'config.yaml'
        config.write_text(yaml.safe_dump(conf))
        with (td / 'collector.log').open('w') as log:
            proc = subprocess.Popen([BINARY, '--config='+str(config)], stdout=log, stderr=log)
            try:
                wait_receiver(http_port, proc)
                provider = TracerProvider()
                provider.add_span_processor(SimpleSpanProcessor(OTLPSpanExporter(endpoint=f'http://127.0.0.1:{http_port}/v1/traces')))
                tracer = provider.get_tracer('policy-tests')
                emit(tracer, 'positive', positive, **popts)
                emit(tracer, 'negative', negative, **nopts)
                # Real SDK false/string gate tests detect accidental truthiness.
                emit(tracer, 'false-gate', positive | {'llm.workflow': False}, **popts)
                emit(tracer, 'string-gate', positive | {'llm.workflow': 'true'}, **popts)
                provider.shutdown()
                time.sleep(1.1)
            finally:
                proc.terminate(); proc.wait(timeout=10)
        names = retained_names(output)
        assert 'positive' in names, (name, names, (td/'collector.log').read_text())
        assert not {'negative', 'false-gate', 'string-gate'} & names, (name, names)
        print('PASS isolated', name, flush=True)
    # Explicit drop must override a simultaneously matching keep.
    sampler['policies'] = [policies['drop-explicit-no-sample'], policies['keep-llm-errors']]
    conf['processors']['tail_sampling'] = sampler
    drop_output = td/'drop.json'
    conf['exporters']['file']['path'] = str(drop_output)
    config.write_text(yaml.safe_dump(conf))
    with (td/'drop.log').open('w') as log:
        proc = subprocess.Popen([BINARY, '--config='+str(config)], stdout=log, stderr=log)
        try:
            wait_receiver(http_port, proc)
            provider = TracerProvider()
            provider.add_span_processor(SimpleSpanProcessor(OTLPSpanExporter(endpoint=f'http://127.0.0.1:{http_port}/v1/traces')))
            tracer = provider.get_tracer('drop-test')
            emit(tracer, 'keep-error', base, error=True)
            emit(tracer, 'drop-error', base | {'app.do_not_sample': True}, error=True)
            provider.shutdown(); time.sleep(1.1)
        finally:
            proc.terminate(); proc.wait(timeout=10)
    assert retained_names(drop_output) == {'keep-error'}, retained_names(drop_output)
    print('PASS drop overrides matching error keep')
print('PASS isolated policy suite; backend delivery and durable recovery remain external gates')
