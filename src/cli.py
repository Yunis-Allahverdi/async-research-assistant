"""Command-line interface.

Usage:
    python -m researcher ask "What is photosynthesis?" [--sources wiki,arxiv,web] [--no-cache]

This module only parses args, calls research(), and prints. All real logic
lives in src/core/researcher.py — that's what makes this file easy to test
without actually running asyncio.run() end to end.
"""

from __future__ import annotations

import argparse
import asyncio

from src.config import get_settings
from src.core.researcher import research
from src.logging_config import setup_logging
from src.models import ResearchResult

# Short, easy-to-type names on the command line map to the origin names
# fetch_source/gather_sources actually expect.
_ORIGIN_MAP = {"wiki": "wikipedia", "arxiv": "arxiv", "web": "web"}


def parse_origins(raw: str) -> list[str]:
    """Turn "wiki,arxiv" into ["wikipedia", "arxiv"]. Raises ValueError on a typo."""
    origins = []
    for part in raw.split(","):
        name = part.strip().lower()
        if name not in _ORIGIN_MAP:
            raise ValueError(
                f"Unknown source {name!r}. Expected one of: wiki, arxiv, web."
            )
        origins.append(_ORIGIN_MAP[name])
    return origins


def build_parser() -> argparse.ArgumentParser:
    """Build the argparse tree: `researcher ask <question> [--sources ...] [--no-cache]`."""
    parser = argparse.ArgumentParser(prog="researcher", description="Async research assistant")
    subparsers = parser.add_subparsers(dest="command", required=True)

    ask = subparsers.add_parser("ask", help="Ask a research question")
    ask.add_argument("question", help="The question to research")
    ask.add_argument(
        "--sources", default="wiki,arxiv,web",
        help="Comma-separated sources to query (wiki, arxiv, web). Default: all three.",
    )
    ask.add_argument(
        "--no-cache", action="store_true",
        help="Bypass the cache and fetch fresh results.",
    )

    return parser


def render_result(result: ResearchResult) -> str:
    """Turn a ResearchResult into the text the user sees on screen."""
    lines = [f"Q: {result.question}", "", f"A: {result.answer.answer}"]

    if result.answer.citations:
        lines.append("")
        lines.append("References:")
        for citation in result.answer.citations:
            lines.append(f"  [{citation.index}] ({citation.source.origin}) {citation.source.title}")
            lines.append(f"      {citation.source.url}")

    if result.degraded:
        failed_origins = [r.origin for r in result.per_source if not r.ok]
        lines.append("")
        lines.append(
            f"Note: {', '.join(failed_origins)} could not be reached, "
            "so this answer may be incomplete."
        )

    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Entry point. Returns a process exit code (0 = success, 1 = error)."""
    settings = get_settings()
    setup_logging(settings)

    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        origins = parse_origins(args.sources)
    except ValueError as e:
        print(f"Error: {e}")
        return 1

    try:
        result = asyncio.run(
            research(
                args.question,
                origins=origins,
                use_cache=not args.no_cache,
                settings=settings,
            )
        )
    except ValueError as e:
        print(f"Error: {e}")
        return 1

    print(render_result(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
