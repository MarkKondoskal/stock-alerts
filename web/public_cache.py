"""Bounded per-worker public read cache; never caches failed reads."""
from copy import deepcopy
from threading import RLock
from time import monotonic

_entries = {}
_lock = RLock()


def cached(key, build):
    with _lock:
        entry = _entries.get(key)
        if entry and monotonic() - entry[0] < 30:
            return deepcopy(entry[1])
        value = build()
        if len(_entries) >= 64:
            _entries.clear()
        _entries[key] = (monotonic(), deepcopy(value))
        return value


def clear():
    with _lock:
        _entries.clear()
