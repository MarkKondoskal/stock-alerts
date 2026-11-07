"""Private notification-attempt journal. Enabled by the workflow environment."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
import uuid


def record(event_id=None, **fields):
    configured = os.environ.get('STOCKALERTS_ALERT_HISTORY_FILE')
    if not configured:
        return None
    path = Path(configured)
    events = json.loads(path.read_text(encoding='utf-8')) if path.exists() else []
    event_id = event_id or str(uuid.uuid4())
    event = next((item for item in events if item['id'] == event_id), None)
    stamp = datetime.now(timezone.utc).isoformat()
    if event is None:
        event = {'id': event_id, 'created_at': stamp}
        events.append(event)
    event.update(fields, updated_at=stamp)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile('w', dir=path.parent, delete=False, encoding='utf-8') as f:
        temp = Path(f.name)
        json.dump(events[-1000:], f, indent=2, allow_nan=False)
    try:
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)
    return event_id


def deliver(send, *, ticker, metric, direction, target, actual):
    event = record(ticker=ticker, metric=metric, direction=direction, target=target,
                   actual=actual, status='pending')
    # Save intent before delivery. Exceptions remain uncertain until investigated.
    try:
        accepted = send()
    except Exception:
        record(event, status='unknown')
        raise
    record(event, status='accepted' if accepted else 'failed_or_unconfirmed')
    return accepted
