from __future__ import annotations

from nvidia_agentic_rag.agents.cache import CachedResponse, TTLResponseCache


def test_cache_hit_and_lru_eviction(monkeypatch) -> None:
    now = [100.0]
    monkeypatch.setattr("nvidia_agentic_rag.agents.cache.time.monotonic", lambda: now[0])
    cache = TTLResponseCache(ttl_seconds=60, max_entries=2)
    cache.put(("a",), CachedResponse(answer="A"))
    cache.put(("b",), CachedResponse(answer="B"))
    assert cache.get(("a",)).answer == "A"
    cache.put(("c",), CachedResponse(answer="C"))
    assert cache.get(("b",)) is None
    assert cache.get(("a",)).answer == "A"


def test_cache_expires(monkeypatch) -> None:
    now = [100.0]
    monkeypatch.setattr("nvidia_agentic_rag.agents.cache.time.monotonic", lambda: now[0])
    cache = TTLResponseCache(ttl_seconds=10, max_entries=2)
    cache.put(("a",), CachedResponse(answer="A"))
    now[0] = 111.0
    assert cache.get(("a",)) is None
