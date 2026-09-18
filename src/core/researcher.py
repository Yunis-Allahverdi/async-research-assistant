"""Business logic: ties validation, concurrent fetching, and synthesis together.

This is the "conductor" of the pipeline:

    question -> validate -> fetch sources concurrently -> synthesize answer
                                                         -> build ResearchResult

Everything else (CLI, benchmark script) should only ever call `research()` —
it never talks to the orchestrator or ai_service directly.
"""

from __future__ import annotations

import logging
import time

from ai import AnswerWithCitations
from src.concurrency.orchestrator import gather_sources
from src.config import Settings
from src.models import ResearchResult
from src.services.ai_service import synthesize_answer

logger = logging.getLogger(__name__)


def validate_question(question: str, *, settings: Settings) -> str:
    """Strip and validate a raw question string.

    Returns the stripped question on success. Raises ValueError (not a stack
    trace) so the CLI can show a clean error message to the user.
    """
    stripped = question.strip()

    if len(stripped) < settings.min_question_len:
        raise ValueError(
            f"Question is too short (min {settings.min_question_len} characters)."
        )
    if len(stripped) > settings.max_question_len:
        raise ValueError(
            f"Question is too long (max {settings.max_question_len} characters)."
        )
    return stripped


async def research(
    question: str,
    *,
    origins: list[str],
    use_cache: bool,
    settings: Settings,
) -> ResearchResult:
    """Run the full pipeline for one question and return a ResearchResult.

    Raises ValueError if the question fails validation (caller's fault, not
    a transient failure, so we don't try to fetch anything first).
    """
    start = time.perf_counter()
    validated = validate_question(question, settings=settings)

    per_source = await gather_sources(
        validated, origins, settings=settings, use_cache=use_cache,
    )

    # Only sources from origins that actually succeeded go to the LLM.
    all_sources = [src for result in per_source if result.ok for src in result.sources]
    degraded = any(not result.ok for result in per_source)

    if not all_sources:
        # No point calling the LLM with zero context — return a clear,
        # honest answer instead of a hallucinated one.
        logger.warning("research: no sources found for %r", validated[:80])
        answer = AnswerWithCitations(
            question=validated,
            answer="No sources could be found for this question, so no answer "
                   "could be generated. Please try rephrasing or check your "
                   "network connection.",
            citations=[],
        )
        return ResearchResult(
            question=validated,
            answer=answer,
            per_source=per_source,
            degraded=True,
            total_elapsed=time.perf_counter() - start,
            from_cache=False,
        )

    answer = synthesize_answer(validated, all_sources, settings=settings)
    total_elapsed = time.perf_counter() - start
    logger.info(
        "research: %r finished in %.2fs (degraded=%s, %d citations)",
        validated[:80], total_elapsed, degraded, len(answer.citations),
    )

    return ResearchResult(
        question=validated,
        answer=answer,
        per_source=per_source,
        degraded=degraded,
        total_elapsed=total_elapsed,
        from_cache=False,
    )
