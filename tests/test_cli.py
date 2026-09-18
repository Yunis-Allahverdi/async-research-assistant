"""Tests for src/cli.py — offline, src.cli.research is mocked (no real network/LLM calls)."""

from __future__ import annotations

import pytest

from ai import Source, Citation, AnswerWithCitations
from src.models import ResearchResult, SourceResult
import src.cli as cli


def _make_result(degraded: bool = False) -> ResearchResult:
    source = Source(title="Wiki title", url="https://en.wikipedia.org/wiki/X",
                     snippet="s", origin="wikipedia")
    answer = AnswerWithCitations(
        question="q", answer="An answer [1].",
        citations=[Citation(index=1, source=source)],
    )
    per_source = [SourceResult(origin="wikipedia", sources=[source], ok=True, elapsed=0.1)]
    if degraded:
        per_source.append(SourceResult(origin="arxiv", ok=False, error="down", elapsed=0.1))

    return ResearchResult(
        question="q", answer=answer, per_source=per_source,
        degraded=degraded, total_elapsed=0.2, from_cache=False,
    )


# --- parse_origins -----------------------------------------------------------

def test_parse_origins_maps_short_names():
    assert cli.parse_origins("wiki,arxiv,web") == ["wikipedia", "arxiv", "web"]


def test_parse_origins_rejects_unknown_name():
    with pytest.raises(ValueError):
        cli.parse_origins("wiki,reddit")


# --- render_result --------------------------------------------------------------

def test_render_result_includes_numbered_references():
    text = cli.render_result(_make_result())
    assert "References:" in text
    assert "[1]" in text
    assert "wikipedia" in text


def test_render_result_notes_degradation():
    text = cli.render_result(_make_result(degraded=True))
    assert "Note:" in text
    assert "arxiv" in text


# --- main(): end-to-end argument parsing + printing, with research() mocked --

def test_main_happy_path_prints_answer_and_references(monkeypatch, capsys):
    async def fake_research(question, *, origins, use_cache, settings):
        return _make_result()

    monkeypatch.setattr(cli, "research", fake_research)

    exit_code = cli.main(["ask", "What is photosynthesis?"])
    out = capsys.readouterr().out

    assert exit_code == 0
    assert "Q:" in out
    assert "References:" in out


def test_main_rejects_unknown_source_before_calling_research(monkeypatch, capsys):
    async def should_not_run(question, *, origins, use_cache, settings):
        raise AssertionError("research() should not be called for a bad --sources value")

    monkeypatch.setattr(cli, "research", should_not_run)

    exit_code = cli.main(["ask", "a valid question", "--sources", "reddit"])
    out = capsys.readouterr().out

    assert exit_code == 1
    assert "Error" in out


def test_main_handles_validation_error_from_research(monkeypatch, capsys):
    async def failing_research(question, *, origins, use_cache, settings):
        raise ValueError("Question is too short (min 3 characters).")

    monkeypatch.setattr(cli, "research", failing_research)

    exit_code = cli.main(["ask", "hi"])
    out = capsys.readouterr().out

    assert exit_code == 1
    assert "Error" in out
