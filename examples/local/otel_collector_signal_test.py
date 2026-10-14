"""Run: python examples/local/otel_collector_signal_test.py /path/to/otelcol-contrib
Real SDK named-log privacy, metric resource promotion and Prometheus labels.
Local fanout file exporters substitute for privileged remote destinations.
"""
import json
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path
import yaml
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import SimpleLogRecordProcessor
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter


def free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0)); return s.getsockname()[1]


assert '0.158.0' in subprocess.check_output([sys.argv[1], '--version'], text=True)
base = Path(__file__).parent
source = yaml.safe_load((base/'otel_collector_routing.yaml').read_text())
receiver_port, metrics_port = free_port(), free_port()
resource = Resource.create({'service.name':'chat-api','deployment.environment.name':'production'})
with tempfile.TemporaryDirectory(prefix='otel-signals-') as temp:
    td = Path(temp)
    conf = {
        'receivers': {'otlp': {'protocols': {'http': {'endpoint': f'127.0.0.1:{receiver_port}'}}}},
        'processors': {k: source['processors'][k] for k in ['attributes/redact_common','attributes/redact_payloads','transform/redact_logs']},
        'exporters': {
            'file/apm': {'path': str(td/'apm.json')},
            'file/rich': {'path': str(td/'rich.json')},
            'file/logs': {'path': str(td/'logs.json')},
            'prometheus': {'endpoint': f'127.0.0.1:{metrics_port}', 'resource_to_telemetry_conversion': {'enabled':True}},
        },
        'service': {'pipelines': {
            'traces/apm': {'receivers':['otlp'],'processors':['attributes/redact_common','attributes/redact_payloads'],'exporters':['file/apm']},
            'traces/rich': {'receivers':['otlp'],'processors':['attributes/redact_common'],'exporters':['file/rich']},
            'logs': {'receivers':['otlp'],'processors':['attributes/redact_common','transform/redact_logs'],'exporters':['file/logs']},
            'metrics': {'receivers':['otlp'],'processors':[],'exporters':['prometheus']},
        }},
    }
    config=td/'config.yaml'; config.write_text(yaml.safe_dump(conf))
    with (td/'collector.log').open('w') as out:
        proc=subprocess.Popen([sys.argv[1], '--config='+str(config)],stdout=out,stderr=out)
        try:
            for _ in range(100):
                if proc.poll() is not None:
                    raise RuntimeError((td/'collector.log').read_text())
                try:
                    with socket.create_connection(('127.0.0.1',receiver_port),timeout=.1): break
                except OSError: time.sleep(.05)
            lp=LoggerProvider(resource=resource)
            lp.add_log_record_processor(SimpleLogRecordProcessor(OTLPLogExporter(endpoint=f'http://127.0.0.1:{receiver_port}/v1/logs')))
            logger=lp.get_logger('named-fixture')
            tp=TracerProvider(resource=resource)
            tp.add_span_processor(SimpleSpanProcessor(OTLPSpanExporter(endpoint=f'http://127.0.0.1:{receiver_port}/v1/traces')))
            with tp.get_tracer('fanout').start_as_current_span('fixture') as span:
                span.set_attribute('http.request.header.authorization','CANARY_SECRET')
                span.set_attribute('gen_ai.input.messages','APP_MASKED_PAYLOAD')
                logger.emit(event_name='app.fixture.failure',body='CANARY_SECRET',attributes={
                    'exception.message':'CANARY_SECRET','gen_ai.input.messages':'CANARY_SECRET',
                    'app.outcome':'error','fixture.boolean':True})
            reader=PeriodicExportingMetricReader(OTLPMetricExporter(endpoint=f'http://127.0.0.1:{receiver_port}/v1/metrics'), export_interval_millis=60000)
            mp=MeterProvider(resource=resource,metric_readers=[reader])
            tokens=mp.get_meter('label-fixture').create_counter('llm.tokens',unit='{token}')
            tokens.add(10,{'http.route':'/chat','gen_ai.token.type':'input','gen_ai.request.model':'fixture-model','gen_ai.provider.name':'fixture'})
            mp.force_flush(); lp.force_flush(); tp.force_flush()
            text=urllib.request.urlopen(f'http://127.0.0.1:{metrics_port}/metrics').read().decode()
            series=next(line for line in text.splitlines() if line.startswith('llm_tokens_total{'))
            for expected in ['http_route="/chat"','gen_ai_token_type="input"','service_name="chat-api"','deployment_environment_name="production"','} 10']:
                assert expected in series,(expected,series)
            mp.shutdown(); lp.shutdown(); tp.shutdown()
            time.sleep(.2)
        finally:
            proc.terminate(); proc.wait(timeout=10)
    logs=(td/'logs.json').read_text()
    apm=(td/'apm.json').read_text(); rich=(td/'rich.json').read_text()
    assert 'CANARY_SECRET' not in logs+apm+rich
    assert 'APP_MASKED_PAYLOAD' not in apm and 'APP_MASKED_PAYLOAD' in rich
    records=[lr for line in logs.splitlines() for rs in json.loads(line)['resourceLogs']
             for sl in rs['scopeLogs'] for lr in sl['logRecords']]
    assert len(records)==1
    record=records[0]
    assert record['eventName']=='app.fixture.failure'
    assert record['body']['stringValue']=='[REDACTED_BY_DEFAULT]'
    assert record['traceId'] and record['spanId']
    assert any(a['key']=='fixture.boolean' and a['value']=={'boolValue':True} for a in record['attributes'])
print('PASS named-log body/attribute privacy, SDK bool type, trace correlation, destination split and actual exported metric labels')
