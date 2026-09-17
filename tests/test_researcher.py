"""Tests for src/core/researcher.py — offline, gather_sources & synthesize_answer mocked."""

from __future__ import annotations

import pytest

from ai import Source, Citation, AnswerWithCitations
from src.config import Settings
from src.models import SourceResult
import src.core.researcher as researcher


def _settings(tmp_path):
    return Settings(cache_dir=str(tmp_path), min_question_len=3, max_question_len=500)


def _fake_synthesize(question, sources, *, settings):
    return AnswerWithCitations(
        question=question,
        answer="A synthesized answer [1].",
        citations=[Citation(index=1, source=sources[0])],
    )


# --- validate_question -------------------------------------------------------

def test_validate_question_strips_and_returns(tmp_path):
    out = researcher.validate_question("  what is photosynthesis?  ", settings=_settings(tmp_path))
    assert out == "what is photosynthesis?"


def test_validate_question_rejects_too_short(tmp_path):
    with pytest.raises(ValueError):
        researcher.validate_question("hi", settings=_settings(tmp_path))


def test_validate_question_rejects_too_long(tmp_path):
    st = Settings(cache_dir=str(tmp_path), max_question_len=10)
    with pytest.raises(ValueError):
        researcher.validate_question("this question is way too long", settings=st)


# --- research: happy path -----------------------------------------------------

@pytest.mark.asyncio
async def test_research_happy_path(tmp_path, monkeypatch):
    async def fake_gather(query, origins, *, settings, use_cache=True):
        return [
            SourceResult(origin=o, sources=[Source(title=o, url=f"https://x.com/{o}",
                                                     snippet="s", origin=o)], ok=True, elapsed=0.1)
            for o in origins
        ]

    monkeypatch.setattr(researcher, "gather_sources", fake_gather)
    monkeypatch.setattr(researcher, "synthesize_answer", _fake_synthesize)

    result = await researcher.research(
        "what is photosynthesis?", origins=["wikipedia", "arxiv", "web"],
        use_cache=True, settings=_settings(tmp_path),
    )

    assert result.answer.answer
    assert len(result.answer.citations) == 1
    assert result.degraded is False


# --- research: validation -----------------------------------------------------

@pytest.mark.asyncio
async def test_research_rejects_invalid_question(tmp_path):
    with pytest.raises(ValueError):
        await researcher.research(
            "hi", origins=["wikipedia"], use_cache=True, settings=_settings(tmp_path),
        )


# --- research: partial failure -> degraded but still answers ------------------

@pytest.mark.asyncio
async def test_research_degrades_when_one_source_fails(tmp_path, monkeypatch):
    async def fake_gather(query, origins, *, settings, use_cache=True):
        return [
            SourceResult(origin="wikipedia", sources=[Source(title="w", url="https://x.com/w",
                                                               snippet="s", origin="wikipedia")],
                         ok=True, elapsed=0.1),
            SourceResult(origin="arxiv", ok=False, error="arxiv is down", elapsed=0.1),
        ]

    monkeypatch.setattr(researcher, "gather_sources", fake_gather)
    monkeypatch.setattr(researcher, "synthesize_answer", _fake_synthesize)

    result = await researcher.research(
        "what is photosynthesis?", origins=["wikipedia", "arxiv"],
        use_cache=True, settings=_settings(tmp_path),
    )

    assert result.degraded is True
    assert result.answer.answer  # an answer was still produced


# --- research: no sources at all -> graceful fallback, no LLM call -----------

@pytest.mark.asyncio
async def test_research_no_sources_skips_llm(tmp_path, monkeypatch):
    async def fake_gather(query, origins, *, settings, use_cache=True):
        return [SourceResult(origin=o, ok=False, error="down", elapsed=0.1) for o in origins]

    llm_calls = {"n": 0}
    def counting_synthesize(question, sources, *, settings):
        llm_calls["n"] += 1
        return _fake_synthesize(question, sources, settings=settings)

    monkeypatch.setattr(researcher, "gather_sources", fake_gather)
    monkeypatch.setattr(researcher, "synthesize_answer", counting_synthesize)

    result = await researcher.research(
        "what is photosynthesis?", origins=["wikipedia", "arxiv"],
        use_cache=True, settings=_settings(tmp_path),
    )

    assert llm_calls["n"] == 0          # LLM was never called
    assert result.degraded is True
    assert result.answer.citations == []
    assert "No sources" in result.answer.answer
