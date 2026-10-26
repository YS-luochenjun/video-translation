"""Read-only historical GLM evidence. No network or inference path."""
from .common import WorkflowError, read_json, require

def context(run, source_sha256):
    path = run / 'analysis/ocr-supplement.json'
    historical = None
    if path.exists():
        data = read_json(path)
        require(data.get('source_sha256') == source_sha256, 'Historical OCR supplement source mismatch')
        historical = 'analysis/ocr-supplement.json'
    return {'status': 'retired', 'provider': 'codex', 'historical_evidence': historical,
            'next': 'codex-packet RUN --stage recognize', 'automatic_pass': False}

def supplement(*args, **kwargs):
    raise WorkflowError('GLM/RapidOCR inference is retired. Use Codex to inspect actual images via codex-packet.')
