"""SE-layer data models.

These are OUR models, separate from the provided ai/ schemas (Source, Citation,
AnswerWithCitations). They carry the extra state our pipeline needs — per-source
timings, degradation flags, cache metadata. No naked dicts cross module
boundaries: everything that moves between modules is one of these typed models.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from ai import Source, AnswerWithCitations


class SourceResult(BaseModel):
    """Outcome of fetching ONE source (origin = wikipedia | arxiv | web).

    The orchestrator produces one of these per source, so the CLI/report can
    show what succeeded, what failed, and how long each took.
    """

    origin: str
    sources: list[Source] = Field(default_factory=list)
    ok: bool = True
    error: str | None = None
    elapsed: float = 0.0


class ResearchResult(BaseModel):
    """Everything the CLI needs to render one research query."""

    question: str
    answer: AnswerWithCitations
    per_source: list[SourceResult] = Field(default_factory=list)
    degraded: bool = False          # True when at least one source failed
    total_elapsed: float = 0.0
    from_cache: bool = False


class CacheEntry(BaseModel):
    """One cached (origin, query) -> sources record, stored as JSON on disk."""

    key: str
    sources: list[Source] = Field(default_factory=list)
    created_at: float               # unix timestamp (time.time())