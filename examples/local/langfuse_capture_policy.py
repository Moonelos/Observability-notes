"""Allowlist fixture: retain bounded diagnostic fields, suppress all raw content."""
import json


def project_tool_result(result):
    # Do not stringify or recursively forward the raw provider/tool result.
    status = result.get('status')
    if status not in ('ok', 'error'):
        status = 'unknown'
    documents = result.get('documents', [])
    if not isinstance(documents, list):
        documents = []
    approved = []
    for doc in documents[:5]:
        if not isinstance(doc, dict):
            continue
        # An application-owned catalog controls allowable IDs/revisions.
        if doc.get('id') == 'doc_001' and doc.get('revision') in ('r3', 'r4'):
            approved.append({'id': 'doc_001', 'revision': doc['revision']})
    return {'status': status, 'documents': approved}


def main():
    raw = {'status': 'ok', 'authorization': 'Bearer DEMO_SECRET_777',
           'documents': [{'id': 'doc_001', 'revision': 'r4',
                          'body': 'contact demo@example.invalid',
                          'nested': [{'token': 'DEMO_SECRET_777'}]}],
           'exception': 'provider failed with DEMO_SECRET_777',
           'messages': ['DEMO_SECRET_777']}
    safe = project_tool_result(raw)
    encoded = json.dumps(safe)
    assert 'DEMO_SECRET_777' not in encoded
    assert 'demo@example.invalid' not in encoded
    assert safe == {'status': 'ok', 'documents': [{'id': 'doc_001', 'revision': 'r4'}]}
    invalid = project_tool_result({'status': 'DEMO_SECRET_777',
                                   'documents': [{'id': 'DEMO_SECRET_777', 'revision': 'r4'}]})
    assert invalid == {'status': 'unknown', 'documents': []}
    print(encoded)
    print('PASS: nested token, header, exception, raw body and attacker-controlled IDs suppressed')


if __name__ == '__main__':
    main()
