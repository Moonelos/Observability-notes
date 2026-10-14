"""No free-text capture by default. This is a policy boundary, not a secret detector."""
def safe_text(value: str, *, limit: int = 2000) -> str:
    # Arbitrary prose has no reliable regex-only secrecy boundary.
    return '[CONTENT OMITTED]' if value else ''


def safe_record(*, status: str, document_ids: list[str]) -> dict:
    if status not in {'answered', 'no_context', 'failed'}:
        raise ValueError('unknown status')
    allowed = {'doc_001', 'doc_002'}
    return {'status': status, 'document_ids': [x for x in document_ids if x in allowed][:5]}
