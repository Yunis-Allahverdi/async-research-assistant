"""Tests for src/services/ai_service.py — all offline, no network.

We mock the ai.* fetchers and ai.synthesize so nothing hits the internet.
`monkeypatch` temporarily swaps a function/dict entry for the duration of one
test, then restores it automatically.
"""

from __future__ import annotations

import asyncio

import pytest

from ai import Source, AnswerWithCitations, Citation
from ai.providers.base import ProviderError
from src.config import Settings
import src.services.ai_service as svc


def _src(origin: str) -> Source:
    return Source(title="T", url="https://x.com", snippet="s", origin=origin)


def _settings(tmp_path):
    # retry_backoff=0 so retries don't actually sleep during the test
    return Settings(cache_dir=str(tmp_path), retry_backoff=0.0,
                    max_retries=3, source_timeout=2.0)


# --- fetch_source: happy path + dispatch -----------------------------------

@pytest.mark.asyncio
async def test_fetch_source_happy_path(tmp_path, monkeypatch):
    async def fake(query, *, max_results=3, client=None):
        return [_src("wikipedia")]
    monkeypatch.setitem(svc._FETCHERS, "wikipedia", fake)

    out = await svc.fetch_source("wikipedia", "photosynthesis", settings=_settings(tmp_path))
    assert len(out) == 1
    assert out[0].origin == "wikipedia"


# --- fetch_source: caching --------------------------------------------------

@pytest.mark.asyncio
async def test_fetch_source_uses_cache_on_second_call(tmp_path, monkeypatch):
    calls = {"n": 0}
    async def counting(query, *, max_results=3, client=None):
        calls["n"] += 1
        return [_src("web")]
    monkeypatch.setitem(svc._FETCHERS, "web", counting)
    st = _settings(tmp_path)

    await svc.fetch_source("web", "same query", settings=st)
    await svc.fetch_source("web", "same query", settings=st)   # should hit cache
    assert calls["n"] == 1        # fetcher called only once


@pytest.mark.asyncio
async def test_fetch_source_no_cache_flag_bypasses_cache(tmp_path, monkeypatch):
    calls = {"n": 0}
    async def counting(query, *, max_results=3, client=None):
        calls["n"] += 1
        return [_src("web")]
    monkeypatch.setitem(svc._FETCHERS, "web", counting)
    st = _settings(tmp_path)

    await svc.fetch_source("web", "q", settings=st, use_cache=False)
    await svc.fetch_source("web", "q", settings=st, use_cache=False)
    assert calls["n"] == 2        # cache skipped both times


# --- fetch_source: retry / error paths -------------------------------------

@pytest.mark.asyncio
async def test_fetch_source_retries_then_succeeds(tmp_path, monkeypatch):
    attempts = {"n": 0}
    async def flaky(query, *, max_results=3, client=None):
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise ProviderError("transient 503")
        return [_src("arxiv")]
    monkeypatch.setitem(svc._FETCHERS, "arxiv", flaky)

    out = await svc.fetch_source("arxiv", "q", settings=_settings(tmp_path), use_cache=False)
    assert attempts["n"] == 3
    assert len(out) == 1


@pytest.mark.asyncio
async def test_fetch_source_reraises_after_exhaustion(tmp_path, monkeypatch):
    async def always_fail(query, *, max_results=3, client=None):
        raise ProviderError("dead")
    monkeypatch.setitem(svc._FETCHERS, "arxiv", always_fail)

    with pytest.raises(ProviderError):
        await svc.fetch_source("arxiv", "q", settings=_settings(tmp_path), use_cache=False)


@pytest.mark.asyncio
async def test_fetch_source_times_out(tmp_path, monkeypatch):
    async def slow(query, *, max_results=3, client=None):
        await asyncio.sleep(5)
        return [_src("web")]
    monkeypatch.setitem(svc._FETCHERS, "web", slow)
    st = Settings(cache_dir=str(tmp_path), retry_backoff=0.0, source_timeout=0.3)

    with pytest.raises(TimeoutError):
        await svc.fetch_source("web", "q", settings=st, use_cache=False)


@pytest.mark.asyncio
async def test_fetch_source_rejects_unknown_origin(tmp_path):
    with pytest.raises(ValueError):
        await svc.fetch_source("reddit", "q", settings=_settings(tmp_path))


# --- synthesize_answer ------------------------------------------------------

def test_synthesize_answer_retries_then_succeeds(tmp_path, monkeypatch):
    attempts = {"n": 0}
    def flaky_syn(question, sources, *, llm=None):
        attempts["n"] += 1
        if attempts["n"] < 2:
            raise ProviderError("llm 429")
        return AnswerWithCitations(question=question, answer="ans [1]",
                                   citations=[Citation(index=1, source=sources[0])])
    monkeypatch.setattr(svc, "ai_synthesize", flaky_syn)

    ans = svc.synthesize_answer("q", [_src("web")], settings=_settings(tmp_path))
    assert attempts["n"] == 2
    assert len(ans.citations) == 1