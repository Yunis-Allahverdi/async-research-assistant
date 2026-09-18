"""Tests for scripts/benchmark.py — offline, fetch_source & gather_sources mocked.

We don't test real network timing here (that would be slow and flaky). We
verify the SHAPE of the benchmark: it calls each origin once sequentially,
once in parallel, computes a speed-up ratio, and never crashes even when a
source fails.
"""

from __future__ import annotations

import asyncio

import pytest

from ai import Source
from src.config import Settings
from src.models import SourceResult
import scripts.benchmark as bench


def _settings(tmp_path):
    return Settings(cache_dir=str(tmp_path))


@pytest.mark.asyncio
async def test_run_sequential_calls_each_origin_once(tmp_path, monkeypatch):
    calls: list[str] = []

    async def fake_fetch_source(origin, query, *, client=None, settings, use_cache=True):
        calls.append(origin)
        assert use_cache is False  # benchmark must bypass the cache
        return [Source(title=origin, url=f"https://x.com/{origin}", snippet="s", origin=origin)]

    monkeypatch.setattr(bench, "fetch_source", fake_fetch_source)

    elapsed, failed = await bench._run_sequential("q", ["wikipedia", "arxiv"], settings=_settings(tmp_path))

    assert calls == ["wikipedia", "arxiv"]
    assert failed == []
    assert elapsed >= 0


@pytest.mark.asyncio
async def test_run_sequential_records_failures_without_crashing(tmp_path, monkeypatch):
    async def flaky(origin, query, *, client=None, settings, use_cache=True):
        if origin == "arxiv":
            raise RuntimeError("boom")
        return [Source(title=origin, url="https://x.com", snippet="s", origin=origin)]

    monkeypatch.setattr(bench, "fetch_source", flaky)

    elapsed, failed = await bench._run_sequential("q", ["wikipedia", "arxiv"], settings=_settings(tmp_path))

    assert failed == ["arxiv"]


@pytest.mark.asyncio
async def test_run_parallel_reports_failed_origins(tmp_path, monkeypatch):
    async def fake_gather(query, origins, *, settings, use_cache=True):
        assert use_cache is False
        return [
            SourceResult(origin="wikipedia", sources=[], ok=True, elapsed=0.1),
            SourceResult(origin="arxiv", ok=False, error="down", elapsed=0.1),
        ]

    monkeypatch.setattr(bench, "gather_sources", fake_gather)

    elapsed, failed = await bench._run_parallel("q", ["wikipedia", "arxiv"], settings=_settings(tmp_path))

    assert failed == ["arxiv"]
    assert elapsed >= 0


def test_main_prints_speedup_and_reproduce_command(monkeypatch, capsys):
    async def fake_sequential(query, origins, *, settings):
        return 6.0, []

    async def fake_parallel(query, origins, *, settings):
        return 3.0, []

    monkeypatch.setattr(bench, "_run_sequential", fake_sequential)
    monkeypatch.setattr(bench, "_run_parallel", fake_parallel)

    exit_code = bench.main(["some question", "--sources", "wiki,arxiv"])
    out = capsys.readouterr().out

    assert exit_code == 0
    assert "sequential: 6.00s" in out
    assert "parallel:   3.00s" in out
    assert "speed-up: 2.0x" in out
    assert "python -m scripts.benchmark" in out


def test_main_rejects_unknown_source(capsys):
    exit_code = bench.main(["q", "--sources", "reddit"])
    out = capsys.readouterr().out

    assert exit_code == 1
    assert "Error" in out
