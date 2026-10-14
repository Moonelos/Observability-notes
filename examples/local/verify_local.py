"""Run real loopback servers, identity/privacy/feedback/propagation and concurrent claim checks."""
import concurrent.futures
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import urllib.error
from result_store import ResultStore
from privacy import safe_text

ROOT = Path(__file__).resolve().parent

def call(port, path, payload, token=None, extra=None):
    headers = {'content-type': 'application/json'}
    if token: headers['authorization'] = 'Bearer ' + token
    headers.update(extra or {})
    req = urllib.request.Request(f'http://127.0.0.1:{port}{path}', data=json.dumps(payload).encode(), headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()

def spans(text):
    decoder = json.JSONDecoder()
    found = []
    for i, c in enumerate(text):
        if c == '{':
            try:
                value, _ = decoder.raw_decode(text[i:])
                if isinstance(value, dict) and 'name' in value and 'context' in value:
                    found.append(value)
            except ValueError: pass
    return found

def main():
    processes = []
    handles = []
    with tempfile.TemporaryDirectory(prefix='observability-local-') as tmp:
        env = os.environ | {'LAB_PUBLIC_TOKEN': 'local-user-token', 'INTERNAL_AGENT_TOKEN': 'local-gateway-token'}
        env.pop('LAB_LANGFUSE_LIVE', None)
        try:
            for module, port, service in [('rag_app', 8083, 'rag-service'), ('agent_service', 8081, 'agent-service'),
                                          ('retrieval_service', 8082, 'retrieval-service'), ('gateway_service', 8080, 'gateway-service')]:
                f = open(Path(tmp) / f'{module}.log', 'w'); handles.append(f)
                child_env = env | {'OTEL_SERVICE_NAME': service, 'RETRIEVAL_SERVICE_URL': 'http://127.0.0.1:8082'}
                processes.append(subprocess.Popen([sys.executable, '-m', 'uvicorn', module + ':app', '--host', '127.0.0.1', '--port', str(port)], cwd=ROOT, env=child_env, stdout=f, stderr=f))
            for port in (8080, 8081, 8082, 8083):
                for retry in range(100):
                    if any(p.poll() is not None for p in processes): raise AssertionError('server startup failed')
                    try:
                        urllib.request.urlopen(f'http://127.0.0.1:{port}/openapi.json', timeout=.2); break
                    except (OSError, urllib.error.URLError): time.sleep(.1)
                else: raise AssertionError('startup timeout')
            assert call(8081, '/run', {'request_id': 'request-0001', 'question': 'SSO'})[0] == 401
            assert call(8080, '/answer', {'question': 'SSO'})[0] == 401
            assert call(8081, '/run', {'request_id': 'request-0001', 'question': 'SSO'}, 'wrong-token')[0] == 401
            code, text = call(8083, '/answer', {'question': 'How do I reset SSO?'}, 'local-user-token')
            assert code == 200; rag = json.loads(text); trace_id = rag['langfuse_trace_id']; assert len(trace_id) == 32
            assert call(8083, f'/answers/{trace_id}/feedback', {'accepted': False, 'comment': 'authorization: Bearer AUDIT_CANARY'},
                        'local-user-token', {'idempotency-key': 'feedback-0001'})[0] == 204
            assert call(8083, f'/answers/{trace_id}/feedback', {'accepted': False, 'comment': 'authorization: Bearer AUDIT_CANARY'},
                        'local-user-token', {'idempotency-key': 'feedback-0001'})[0] == 204
            assert call(8083, f'/answers/{trace_id}/feedback', {'accepted': True}, 'local-user-token', {'idempotency-key': 'feedback-0001'})[0] == 409
            assert call(8083, '/answers/' + '0'*32 + '/feedback', {'accepted': True}, 'local-user-token', {'idempotency-key': 'feedback-0002'})[0] == 404
            assert json.loads(call(8083, '/answer', {'question': 'EMPTY'}, 'local-user-token')[1])['status'] == 'no_context'
            assert call(8083, '/answer', {'question': 'authorization: Bearer AUDIT_CANARY'}, 'local-user-token')[0] == 200
            code, text = call(8080, '/chat', {'question': 'SSO'}, 'local-user-token', {'baggage': 'app.tenant.tier=attacker'})
            assert code == 200; gateway = json.loads(text); assert gateway['steps'] == 2 and gateway['tier'] == 'enterprise'
            assert 'AUDIT_CANARY' not in safe_text('authorization: Bearer AUDIT_CANARY')
            # Controlled overlap forces follower to meet the running state, not a cache hit.
            store = ResultStore(); entered = threading.Event(); release = threading.Event(); executions = []
            def operation():
                executions.append(1); entered.set(); release.wait(3); return {'answer': 'once'}
            with concurrent.futures.ThreadPoolExecutor(2) as pool:
                first = pool.submit(store.run, 'key', {'q': 'SSO'}, operation)
                assert entered.wait(1)
                second = pool.submit(store.run, 'key', {'q': 'SSO'}, operation)
                time.sleep(.1); assert not second.done(); release.set()
                assert first.result() == second.result() and len(executions) == 1
            print('PASS HTTP auth 401, RAG /answer 200, feedback 204 replay/409 conflict/404 ownership, empty context, concurrent claim single execution')
        finally:
            for p in processes: p.terminate()
            for p in processes:
                try: p.wait(10)
                except subprocess.TimeoutExpired: p.kill(); p.wait()
            for f in handles: f.close()
        texts = {m: (Path(tmp) / f'{m}.log').read_text() for m in ['rag_app','gateway_service','agent_service','retrieval_service']}
        for m, text in texts.items():
            assert 'AUDIT_CANARY' not in text, (m, 'privacy canary leaked')
        exported = {m: spans(t) for m,t in texts.items()}
        tid = '0x' + gateway['langfuse_trace_id']
        for module in ['gateway_service','agent_service','retrieval_service']:
            assert any(s['context']['trace_id'] == tid for s in exported[module]), (module, 'missing connected trace')
        retrieval = next(s for s in exported['retrieval_service'] if s['name'] == 'vector_db.query' and s['context']['trace_id'] == tid)
        if os.getenv('LAB_DISABLE_TIER') == '1':
            assert 'app.tenant.tier' not in retrieval['attributes']
            print('PASS disabling enrichment keeps parentage while removing retrieval tier')
        else:
            assert retrieval['attributes']['app.tenant.tier'] == 'enterprise'
        print('PASS three-service shared trace_id, trusted enterprise enrichment, no secret canary in any export')
        print('Scope: real SDK and HTTP, console export/local scores; external Langfuse and durable restart recovery not verified')

if __name__ == '__main__': main()
