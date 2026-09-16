"""Tests for the filesystem JSON cache (src/storage/cache_store.py)."""

from __future__ import annotations

import time

import pytest

from ai import Source
from src.config import Settings
from src.models import CacheEntry
from src.storage.cache_store import make_key, read, write


def _settings(tmp_path, ttl=86_400):
    """A Settings pointing the cache at a fresh temp dir for this test."""
    return Settings(cache_dir=str(tmp_path), cache_ttl=ttl)


def _sample_entry(key):
    return CacheEntry(
        key=key,
        sources=[Source(title="T", url="https://x.com", snippet="hello", origin="web")],
        created_at=time.time(),
    )


# --- make_key -------------------------------------------------------------

def test_make_key_is_case_insensitive():
    """'What is X?' and 'what is x' must produce the same key."""
    a = make_key("wikipedia", "What is Photosynthesis?")
    b = make_key("wikipedia", "what is photosynthesis?")
    assert a == b


def test_make_key_differs_by_origin():
    """Same query, different source -> different key."""
    assert make_key("wikipedia", "photosynthesis") != make_key("web", "photosynthesis")


# --- write + read (round trip) -------------------------------------------

def test_write_then_read_returns_same_sources(tmp_path):
    """A fresh entry we wrote is read back with its sources intact (cache HIT)."""
    settings = _settings(tmp_path)
    key = make_key("web", "test query")
    write(_sample_entry(key), settings=settings)

    entry = read(key, settings=settings)
    assert entry is not None
    assert entry.sources[0].title == "T"


def test_read_missing_key_returns_none(tmp_path):
    """A key that was never written is a cache MISS -> None."""
    settings = _settings(tmp_path)
    assert read(make_key("web", "never seen"), settings=settings) is None


def test_read_expired_entry_returns_none(tmp_path):
    """An entry older than the TTL is treated as a MISS -> None."""
    settings = _settings(tmp_path, ttl=0)   # everything is instantly 'too old'
    key = make_key("web", "test query")
    write(_sample_entry(key), settings=settings)

    assert read(key, settings=settings) is None