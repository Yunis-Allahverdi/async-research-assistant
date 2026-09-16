"""Central logging setup. Call setup_logging() once at program start (in the CLI).

Everything else just does `logger = logging.getLogger(__name__)` and logs.
Level is driven by config (settings.log_level), so no print() anywhere.
"""

from __future__ import annotations

import logging

from src.config import Settings


def setup_logging(settings: Settings) -> None:
    """Configure the root logger once, using the level from config."""
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )