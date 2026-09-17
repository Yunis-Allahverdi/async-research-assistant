"""Sequential vs. parallel source-fetch benchmark — the headline number for the README.

Usage (run as a module so `src.*` imports resolve from the repo root):
    python -m scripts.benchmark "What is photosynthesis?" --sources wiki,arxiv,web

Always bypasses the cache (use_cache=False), because a cached second run would
return almost instantly and make the comparison meaningless — we want to
measure real network time both ways.

- "sequential" = call fetch_source for each origin ONE AFTER ANOTHER.
  Total time is close to the SUM of each origin's time.
- "parallel"   = call gather_sources, which fires all origins AT ONCE.
  Total time is close to the MAX of each origin's time.
"""

from __future__ import annotations

import argparse
import asyncio
import time

from src.cli import parse_origins
from src.concurrency.orchestrator import gather_sources
from src.config import get_settings
from src.logging_config import setup_logging
from src.services.ai_service import fetch_source


async def _run_sequential(query: str, origins: list[str], *, settings) -> tuple[float, list[str]]:
    """Fetch each origin one after another. Returns (total_seconds, failed_origins)."""
    failed: list[str] = []
    start = time.perf_counter()
    for origin in origins:
        try:
            await fetch_source(origin, query, settings=settings, use_cache=False)
        except Exception:
            failed.append(origin)
    return time.perf_counter() - start, failed


async def _run_parallel(query: str, origins: list[str], *, settings) -> tuple[float, list[str]]:
    """Fetch all origins at once via gather_sources. Returns (total_seconds, failed_origins)."""
    start = time.perf_counter()
    results = await gather_sources(query, origins, settings=settings, use_cache=False)
    elapsed = time.perf_counter() - start
    failed = [r.origin for r in results if not r.ok]
    return elapsed, failed


async def _run_benchmark(query: str, origins: list[str], sources_arg: str) -> None:
    settings = get_settings()
    setup_logging(settings)

    print(f"Benchmarking {query!r} against: {', '.join(origins)}\n")

    seq_time, seq_failed = await _run_sequential(query, origins, settings=settings)
    note = f"  (failed: {', '.join(seq_failed)})" if seq_failed else ""
    print(f"sequential: {seq_time:.2f}s{note}")

    par_time, par_failed = await _run_parallel(query, origins, settings=settings)
    note = f"  (failed: {', '.join(par_failed)})" if par_failed else ""
    print(f"parallel:   {par_time:.2f}s{note}")

    speedup = seq_time / par_time if par_time > 0 else float("inf")
    print(f"\nspeed-up: {speedup:.1f}x")
    print(f"\nreproduce with:\n  python -m scripts.benchmark {query!r} --sources {sources_arg}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sequential vs. parallel source-fetch benchmark")
    parser.add_argument(
        "question", nargs="?", default="What is photosynthesis?",
        help="Query to benchmark (default: a sample question)",
    )
    parser.add_argument(
        "--sources", default="wiki,arxiv,web",
        help="Comma-separated sources to benchmark (wiki, arxiv, web)",
    )
    args = parser.parse_args(argv)

    try:
        origins = parse_origins(args.sources)
    except ValueError as e:
        print(f"Error: {e}")
        return 1

    asyncio.run(_run_benchmark(args.question, origins, args.sources))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
