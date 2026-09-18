"""Tests for src/concurrency/orchestrator.py — offline, fetch_source is mocked."""

from __future__ import annotations

import asyncio

import pytest

from ai import Source
from src.config import Settings
import src.concurrency.orchestrator as orch


def _settings(tmp_path):
    return Settings(cache_dir=str(tmp_path), source_timeout=2.0, max_concurrency=5)


@pytest.mark.asyncio
async def test_gather_sources_one_fails_others_succeed(tmp_path, monkeypatch):
    async def fake_fetch_source(origin, query, *, client=None, settings, use_cache=True):
        if origin == "arxiv":
            raise RuntimeError("arxiv is down")
        return [Source(title=f"{origin} title", url=f"https://example.com/{origin}",
                        snippet="s", origin=origin)]

    monkeypatch.setattr(orch, "fetch_source", fake_fetch_source)

    results = await orch.gather_sources(
        "test query", ["wikipedia", "arxiv", "web"], settings=_settings(tmp_path),
    )

    assert len(results) == 3
    by_origin = {r.origin: r for r in results}
    assert by_origin["wikipedia"].ok is True
    assert by_origin["web"].ok is True
    assert by_origin["arxiv"].ok is False
    assert "arxiv is down" in by_origin["arxiv"].error


@pytest.mark.asyncio
async def test_gather_sources_runs_concurrently_not_sequentially(tmp_path, monkeypatch):
    async def slow_fetch(origin, query, *, client=None, settings, use_cache=True):
        await asyncio.sleep(0.2)
        return [Source(title=origin, url="https://x.com", snippet="s", origin=origin)]

    monkeypatch.setattr(orch, "fetch_source", slow_fetch)

    import time
    start = time.perf_counter()
    results = await orch.gather_sources(
        "q", ["wikipedia", "arxiv", "web"], settings=_settings(tmp_path),
    )
    elapsed = time.perf_counter() - start

    assert all(r.ok for r in results)
    # would take ~0.6s if sequential; concurrent should be close to ~0.2s
    assert elapsed < 0.5


@pytest.mark.asyncio
async def test_gather_sources_respects_timeout(tmp_path, monkeypatch):
    async def hangs_forever(origin, query, *, client=None, settings, use_cache=True):
        await asyncio.sleep(5)
        return []

    monkeypatch.setattr(orch, "fetch_source", hangs_forever)
    st = Settings(cache_dir=str(tmp_path), source_timeout=0.2, max_concurrency=5)

    results = await orch.gather_sources("q", ["wikipedia"], settings=st)

    assert results[0].ok is False
    assert "timeout" in results[0].error
