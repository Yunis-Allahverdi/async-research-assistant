"""Thin entry point so `python -m researcher ask "..."` works.

All real logic lives in src/cli.py — this file only exists because Python's
`-m` flag looks for a package's __main__.py.
"""

from src.cli import main

raise SystemExit(main())
