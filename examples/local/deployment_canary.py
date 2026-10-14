"""Loopback-only Collector delivery, backend-failure and TLS/auth lab.
Run: python3 deployment_canary.py /path/to/otelcol-contrib [--secure]
No real backend, cluster, credentials, or containers are contacted.
"""
import argparse, base64, hashlib, http.server, json, os, pathlib, ssl
import subprocess, tempfile, threading, time, urllib.error, urllib.request

parser = argparse.ArgumentParser()
parser.add_argument('collector')
parser.add_argument('--secure', action='store_true')
parser.add_argument('--persistent', action='store_true')
args = parser.parse_args()
root = pathlib.Path(tempfile.mkdtemp(prefix='deployment-canary-'))
receipts = []
mode = {'status': 200}
class Backend(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        data = self.rfile.read(int(self.headers.get('Content-Length', 0)))
        status = mode['status']
        if status == 200:
            receipts.append(json.loads(data))
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(b'{}')
    def log_message(self, *a):
        pass
server = http.server.ThreadingHTTPServer(('127.0.0.1', 19480), Backend)
threading.Thread(target=server.serve_forever, daemon=True).start()
extra = ''
transport = ''
scheme = 'http'
if args.secure:
    subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes',
        '-keyout', str(root/'key.pem'), '-out', str(root/'cert.pem'), '-days', '1',
        '-subj', '/CN=localhost', '-addext', 'subjectAltName=DNS:localhost'],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    digest = base64.b64encode(hashlib.sha1(b'lab-only').digest()).decode()
    (root/'htpasswd').write_text('canary:{SHA}'+digest+'\n')
    extra = f'  basicauth/server:\n    htpasswd:\n      file: {root}/htpasswd\n'
    transport = f'''        tls:
          cert_file: {root}/cert.pem
          key_file: {root}/key.pem
        auth:
          authenticator: basicauth/server
'''
    scheme = 'https'
if args.persistent:
    (root/'queue').mkdir()
    extra += f'  file_storage:\n    directory: {root}/queue\n'
storage = '      storage: file_storage\n' if args.persistent else ''
config = f'''extensions:
  health_check:
    endpoint: 127.0.0.1:19433
{extra}receivers:
  otlp:
    protocols:
      http:
        endpoint: 127.0.0.1:19418
{transport}exporters:
  otlphttp/backend:
    endpoint: http://127.0.0.1:19480
    encoding: json
    compression: none
    sending_queue:
      queue_size: 100
{storage}    retry_on_failure:
      initial_interval: 1s
      max_interval: 1s
      max_elapsed_time: 5s
service:
  extensions: [health_check{', basicauth/server' if args.secure else ''}{', file_storage' if args.persistent else ''}]
  telemetry:
    metrics:
      readers:
        - pull:
            exporter:
              prometheus:
                host: 127.0.0.1
                port: 19488
  pipelines:
    traces:
      receivers: [otlp]
      processors: []
      exporters: [otlphttp/backend]
'''
(root/'collector.yaml').write_text(config)
subprocess.run([args.collector,'validate','--config='+str(root/'collector.yaml')],check=True)
log = open(root/'collector.log','w')
proc = subprocess.Popen([args.collector,'--config='+str(root/'collector.yaml')],stdout=log,stderr=log)
ctx = ssl.create_default_context(cafile=str(root/'cert.pem')) if args.secure else None
def post(number, authorization=None, context=ctx):
    now = time.time_ns()
    body = {'resourceSpans':[{'resource':{'attributes':[{'key':'service.name','value':{'stringValue':'deployment-smoke-test'}}]},'scopeSpans':[{'scope':{'name':'deployment-lab'},'spans':[{'traceId':f'{number:032x}','spanId':f'{number:016x}','name':'deployment-canary','startTimeUnixNano':str(now),'endTimeUnixNano':str(now+1000000)}]}]}]}
    headers = {'Content-Type':'application/json'}
    if authorization: headers['Authorization'] = authorization
    req = urllib.request.Request(f'{scheme}://localhost:19418/v1/traces',json.dumps(body).encode(),headers)
    try:
        with urllib.request.urlopen(req,context=context,timeout=3) as response:
            return response.status
    except urllib.error.HTTPError as error:
        return error.code
try:
    for _ in range(60):
        try:
            urllib.request.urlopen('http://127.0.0.1:19433/',timeout=1).close(); break
        except Exception: time.sleep(.1)
    token = 'Basic '+base64.b64encode(b'canary:lab-only').decode() if args.secure else None
    if args.secure:
        before = len(receipts)
        assert post(1) == 401
        assert post(1,'Basic '+base64.b64encode(b'canary:wrong').decode()) == 401
        try:
            post(1,token,ssl.create_default_context())
            raise AssertionError('Untrusted certificate accepted')
        except urllib.error.URLError:
            pass
        time.sleep(.2)
        assert len(receipts) == before
        print('HOSTILE missing/wrong auth=401; untrusted TLS rejected; backend receipts=0')
    assert post(2,token) == 200
    for _ in range(50):
        if receipts: break
        time.sleep(.1)
    resource_attrs = receipts[0]['resourceSpans'][0]['resource']['attributes']
    assert any(a['key'] == 'service.name' and a['value'].get('stringValue') == 'deployment-smoke-test' for a in resource_attrs)
    assert receipts[0]['resourceSpans'][0]['scopeSpans'][0]['spans'][0]['traceId'] == f'{2:032x}'
    print('INTENDED trace=00000000000000000000000000000002 backend receipt=1')
    mode['status'] = 503
    assert post(3,token) == 200
    time.sleep(1.3)
    assert len(receipts) == 1
    if args.persistent:
        proc.terminate(); proc.wait(timeout=10)
        proc = subprocess.Popen([args.collector,'--config='+str(root/'collector.yaml')],stdout=log,stderr=log)
        time.sleep(1)
        print('PERSISTENCE restarted Collector with same file_storage directory')
    mode['status'] = 200
    for _ in range(50):
        if len(receipts) == 2: break
        time.sleep(.1)
    assert len(receipts) == 2
    assert receipts[1]['resourceSpans'][0]['scopeSpans'][0]['spans'][0]['traceId'] == f'{3:032x}'
    print('503 ingress accepted; delivery delayed; restored backend receipt=2')
    mode['status'] = 401
    assert post(4,token) == 200
    time.sleep(1)
    mode['status'] = 200
    time.sleep(1)
    assert len(receipts) == 2
    print('401 ingress accepted; permanent backend rejection; no recovered receipt')
    metrics = urllib.request.urlopen('http://127.0.0.1:19488/metrics').read().decode()
    print('\n'.join(line for line in metrics.splitlines() if line.startswith(('otelcol_receiver_accepted_spans','otelcol_exporter_sent_spans','otelcol_exporter_send_failed_spans'))))
finally:
    proc.terminate(); proc.wait(timeout=10); server.shutdown(); log.close()
    print('Artifacts:',root)
