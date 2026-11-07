"""Select precomputed results only while their account inputs and age match."""
import base64
import gzip
import hashlib
import json
from datetime import datetime, timezone

PATH = 'portfolio/dashboard_snapshot.json'


def digest(document):
    return hashlib.sha256(json.dumps(document, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def select(bundle, section, key, us=None, dk=None, now=None):
    if not isinstance(bundle, dict) or bundle.get('schema') != 1:
        return None
    try:
        current = now or datetime.now(timezone.utc)
        age = (current - datetime.fromisoformat(bundle['generated_at'])).total_seconds()
        limit = 96*3600 if current.weekday() >= 5 or (current.weekday() == 0 and current.hour < 7) else 7200
        if not 0 <= age <= limit:
            return None
        if us is not None and bundle.get('accounts') != [digest(us), digest(dk)]:
            return None
        return bundle.get(section, {}).get(key)
    except (ValueError, KeyError, TypeError):
        return None


def pack(bundle):
    raw = json.dumps(bundle, separators=(',', ':'), allow_nan=False).encode()
    return {'encoding': 'gzip-base64', 'generated_at': bundle['generated_at'],
            'data': base64.b64encode(gzip.compress(raw)).decode()}


def unpack(document):
    if document.get('encoding') == 'gzip-base64':
        return json.loads(gzip.decompress(base64.b64decode(document['data'])))
    return document
