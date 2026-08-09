from __future__ import annotations

import threading
import time
from collections import OrderedDict
from dataclasses import dataclass


@dataclass(frozen=True)
class RetrievalCacheEntry:
    payload: str
    created_at: float


class SecureRetrievalCache:
    """Small tenant/auth scoped retrieval cache for derived evidence payloads."""

    def __init__(self, *, ttl_seconds: float, max_entries: int) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        if max_entries <= 0:
            raise ValueError("max_entries must be positive")
        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries
        self._entries: OrderedDict[tuple[str, ...], RetrievalCacheEntry] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: tuple[str, ...]) -> str | None:
        with self._lock:
            self._evict_expired_locked()
            entry = self._entries.get(key)
            if entry is None:
                return None
            self._entries.move_to_end(key)
            return entry.payload

    def put(self, key: tuple[str, ...], payload: str) -> None:
        with self._lock:
            self._evict_expired_locked()
            self._entries[key] = RetrievalCacheEntry(
                payload=payload,
                created_at=time.monotonic(),
            )
            self._entries.move_to_end(key)
            while len(self._entries) > self.max_entries:
                self._entries.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def _evict_expired_locked(self) -> None:
        now = time.monotonic()
        expired = [
            key
            for key, value in self._entries.items()
            if now - value.created_at >= self.ttl_seconds
        ]
        for key in expired:
            self._entries.pop(key, None)
