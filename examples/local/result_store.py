"""Process-local atomic in-flight claims for a loopback lab, not durable exactly-once."""
import hashlib
import json
import threading
import time
from fastapi import HTTPException

class ResultStore:
    def __init__(self):
        self.condition = threading.Condition()
        self.rows = {}

    def run(self, key, payload, operation):
        fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        deadline = time.monotonic() + 5
        with self.condition:
            while key in self.rows:
                row = self.rows[key]
                if row['fingerprint'] != fingerprint:
                    raise HTTPException(409, 'request payload conflict')
                if row['state'] == 'completed':
                    return row['result']
                if row['state'] == 'failed':
                    raise HTTPException(503, 'prior attempt failed; new request required')
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise HTTPException(503, 'request still running')
                self.condition.wait(remaining)
            # Claim is atomic with the lookup. Only its owner leaves to perform work.
            self.rows[key] = {'fingerprint': fingerprint, 'state': 'running'}
        try:
            result = operation()
        except BaseException:
            with self.condition:
                self.rows[key]['state'] = 'failed'
                self.condition.notify_all()
            raise
        with self.condition:
            self.rows[key].update(state='completed', result=result)
            self.condition.notify_all()
        return result
