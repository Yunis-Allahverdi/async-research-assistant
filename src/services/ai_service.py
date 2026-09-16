"""Service layer around the provided ai/ module.

The ai/ package is thin: it fetches and synthesizes, but has no retries, no
timeouts, no logging, no caching. This module adds all of that WITHOUT touching
ai/. Everything else in our code calls these two functions instead of ai.*
directly.
"""

from __future__ import annotations

import asyncio
import logging
import time

from tenacity import (
    AsyncRetrying,
    Retrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from ai import (
    Source,
    AnswerWithCitations,
    fetch_wikipedia,
    fetch_arxiv,
    fetch_web,
    synthesize as ai_synthesize,
)
from ai.providers.base import ProviderError
from src.config import Settings
from src.models import CacheEntry
from src.storage.cache_store import make_key, read, write

logger = logging.getLogger(__name__)

DEFAULT_MAX_RESULTS = 3

# Which ai.* coroutine handles each origin. All share the same call shape:
# fetcher(query, *, max_results=..., client=...).
_FETCHERS = {
    "wikipedia": fetch_wikipedia,
    "arxiv": fetch_arxiv,
    "web": fetch_web,
}


async def _fetch_with_retry(fetcher, query, *, client, settings):
    """Call one ai.* fetcher with a per-attempt timeout and exponential backoff.

    We retry ONLY ProviderError (the ai/ layer's transient failure: network,
    5xx, 429). A timeout surfaces to the caller so the orchestrator can degrade.
    """
    retryer = AsyncRetrying(
        stop=stop_after_attempt(settings.max_retries),
        wait=wait_exponential(multiplier=settings.retry_backoff),
        retry=retry_if_exception_type(ProviderError),
        reraise=True,
        before_sleep=lambda rs: logger.warning(
            "retrying (%d/%d) after: %s",
            rs.attempt_number, settings.max_retries, rs.outcome.exception(),
        ),
    )
    async for attempt in retryer:
        with attempt:
            async with asyncio.timeout(settings.source_timeout):
                return await fetcher(query, max_results=DEFAULT_MAX_RESULTS, client=client)


async def fetch_source(
    origin: str,
    query: str,
    *,
    client=None,
    settings: Settings,
    use_cache: bool = True,
) -> list[Source]:
    """Fetch sources for one origin, with caching, retry, timeout, and logging.

    origin must be 'wikipedia', 'arxiv', or 'web'.
    """
    key = make_key(origin, query)

    if use_cache:
        cached = read(key, settings=settings)
        if cached is not None:
            logger.info("cache hit: %s %r (%d sources)", origin, query[:80], len(cached.sources))
            return cached.sources

    fetcher = _FETCHERS.get(origin)
    if fetcher is None:
        raise ValueError(f"unknown origin {origin!r} (expected wikipedia|arxiv|web)")

    start = time.perf_counter()
    sources = await _fetch_with_retry(fetcher, query, client=client, settings=settings)
    elapsed = time.perf_counter() - start
    logger.info("fetched %s %r -> %d sources in %.2fs", origin, query[:80], len(sources), elapsed)

    if use_cache and sources:
        write(CacheEntry(key=key, sources=sources, created_at=time.time()), settings=settings)

    return sources


def synthesize_answer(
    question: str,
    sources: list[Source],
    *,
    settings: Settings,
) -> AnswerWithCitations:
    """Wrap ai.synthesize with retry + logging.

    ai.synthesize raises ValueError for empty question/sources (a caller bug, not
    transient) so we don't retry those — only ProviderError from the LLM.
    """
    retryer = Retrying(
        stop=stop_after_attempt(settings.max_retries),
        wait=wait_exponential(multiplier=settings.retry_backoff),
        retry=retry_if_exception_type(ProviderError),
        reraise=True,
        before_sleep=lambda rs: logger.warning(
            "synthesize retry (%d/%d): %s",
            rs.attempt_number, settings.max_retries, rs.outcome.exception(),
        ),
    )
    start = time.perf_counter()
    answer: AnswerWithCitations | None = None
    for attempt in retryer:
        with attempt:
            answer = ai_synthesize(question, sources)
    elapsed = time.perf_counter() - start
    logger.info("synthesized %r in %.2fs (%d citations)", question[:80], elapsed, len(answer.citations))
    return answer