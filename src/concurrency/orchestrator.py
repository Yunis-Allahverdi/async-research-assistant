"""Concurrency orchestration: fetch several sources at the same time, safely.

The question this module answers: "How do I query Wikipedia, arXiv, and the
web all AT ONCE, without one failure breaking all of them?"

Tools used here:
- asyncio.gather(..., return_exceptions=True) -> runs several coroutines
  concurrently and collects their RESULTS (or exceptions) instead of stopping
  at the first failure.
- asyncio.Semaphore(n) -> allows at most `n` requests to be in flight at once
  (so we respect the free APIs' rate limits).
- asyncio.timeout(seconds) -> a total time ceiling for ONE source, including
  all of its retries. This differs from ai_service.fetch_source's own inner
  timeout, which applies per ATTEMPT — this one applies to the source's
  TOTAL time.
- one shared httpx.AsyncClient -> instead of opening 3 separate connections,
  every fetch shares the same connection pool.
"""

from __future__ import annotations

import asyncio
import logging
import time

import httpx

from src.config import Settings
from src.models import SourceResult
from src.services.ai_service import fetch_source

logger = logging.getLogger(__name__)


async def _fetch_one(
    origin: str,
    query: str,
    *,
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
    settings: Settings,
    use_cache: bool,
) -> SourceResult:
    """Fetch ONE source and ALWAYS return a SourceResult — never raises.
    This way the caller (gather_sources) never has to write a separate
    try/except for each source.
    """
    start = time.perf_counter()

    async with semaphore:  # waits here if all slots are busy
        try:
            async with asyncio.timeout(settings.source_timeout):
                sources = await fetch_source(
                    origin,
                    query,
                    client=client,
                    settings=settings,
                    use_cache=use_cache,
                )
            elapsed = time.perf_counter() - start
            logger.info(
                "orchestrator: %s OK in %.2fs (%d sources found)",
                origin, elapsed, len(sources),
            )
            return SourceResult(origin=origin, sources=sources, ok=True, elapsed=elapsed)

        except TimeoutError:
            elapsed = time.perf_counter() - start
            error = f"no response within {settings.source_timeout}s (timeout)"
            logger.warning("orchestrator: %s FAILED (%s)", origin, error)
            return SourceResult(origin=origin, ok=False, error=error, elapsed=elapsed)

        except Exception as e:
            elapsed = time.perf_counter() - start
            logger.warning("orchestrator: %s FAILED (%s)", origin, e)
            return SourceResult(origin=origin, ok=False, error=str(e), elapsed=elapsed)


async def gather_sources(
    query: str,
    origins: list[str],
    *,
    settings: Settings,
    use_cache: bool = True,
) -> list[SourceResult]:
    """Fetch every source in `origins` CONCURRENTLY.

    The returned list is in the same order as `origins`. A failure in one
    source never blocks the others' results.
    """
    semaphore = asyncio.Semaphore(settings.max_concurrency)

    async with httpx.AsyncClient() as client:  # ONE shared connection pool
        tasks = [
            _fetch_one(
                origin, query,
                client=client, semaphore=semaphore,
                settings=settings, use_cache=use_cache,
            )
            for origin in origins
        ]
        # return_exceptions=True: _fetch_one never raises on its own, but this
        # keeps an extra safety net in place regardless.
        results = await asyncio.gather(*tasks, return_exceptions=True)

    out: list[SourceResult] = []
    for origin, result in zip(origins, results):
        if isinstance(result, BaseException):
            # Should be unreachable in practice (_fetch_one catches everything),
            # but convert any unexpected exception into a SourceResult anyway.
            logger.warning("orchestrator: %s failed unexpectedly (%s)", origin, result)
            out.append(SourceResult(origin=origin, ok=False, error=str(result)))
        else:
            out.append(result)

    return out
