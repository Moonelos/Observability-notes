"""Reproduce the documented process lifecycle in a fresh interpreter."""
import os
from pathlib import Path
import re
import subprocess
import sys

note = Path(__file__).resolve().parents[2] / 'opentelemetry/02_python_instrumentation.md'
blocks = re.findall(r'```python\n(.*?)```', note.read_text(), re.S)
source = next(x for x in blocks if x.startswith('# observability.py'))
probe = '''
a = configure_otel()
b = configure_otel()
assert a is b
assert trace.get_tracer_provider() is a.tracer_provider
assert metrics.get_meter_provider() is a.meter_provider
assert a.tracer_provider.resource.attributes['service.instance.id'] == a.meter_provider._sdk_config.resource.attributes['service.instance.id']
print(a.tracer_provider.resource.attributes['service.instance.id'])
shutdown_otel()
shutdown_otel()
try:
    configure_otel()
except RuntimeError:
    print('PASS repeated configure shares handles; shutdown repeat no-op; terminal reconfigure rejected')
else:
    raise AssertionError('stopped global provider incorrectly recreated')
'''
env = os.environ | {'OTEL_SERVICE_NAME': 'bootstrap-test'}
outputs = []
for i in range(2):
    done = subprocess.run([sys.executable, '-c', source + probe], env=env, text=True, capture_output=True)
    assert done.returncode == 0, done.stderr
    assert 'Overriding' not in done.stderr
    outputs.append(done.stdout.splitlines()[0])
    print(done.stdout.strip())
assert outputs[0] != outputs[1]
print('PASS independent process instance IDs differ')
