"""Loopback-only teaching identity fixture; production replaces token/session storage."""
import os
import secrets
from dataclasses import dataclass
from fastapi import Header, HTTPException

@dataclass(frozen=True)
class Identity:
    user_id: str
    tenant_id: str
    account_id: str
    session_id: str

ACCOUNTS = {'account-a': {'tier': 'enterprise', 'region': 'eu'},
            'account-b': {'tier': 'standard', 'region': 'us'}}

def require_identity(authorization: str | None = Header(default=None)) -> Identity:
    token = os.environ.get('LAB_PUBLIC_TOKEN')
    if not token:
        raise HTTPException(503, 'local identity not configured')
    if not secrets.compare_digest(authorization or '', 'Bearer ' + token):
        raise HTTPException(401, 'identity required')
    return Identity('user-a', 'tenant-a', 'account-a', 'session-a')

def require_gateway(authorization: str | None = Header(default=None)) -> Identity:
    token = os.environ.get('INTERNAL_AGENT_TOKEN')
    if not token:
        raise HTTPException(503, 'gateway identity not configured')
    if not secrets.compare_digest(authorization or '', 'Bearer ' + token):
        raise HTTPException(401, 'gateway identity required')
    # This token is deliberately bound to one fixture account. No caller field
    # or baggage can select another account. Real gateways use verified scoped claims.
    return Identity('user-a', 'tenant-a', 'account-a', 'session-a')
