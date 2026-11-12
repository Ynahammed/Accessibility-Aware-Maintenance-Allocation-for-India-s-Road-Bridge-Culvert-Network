"""Vercel entry point: the FastAPI app lives in ``rra.api``.

Vercel discovers this file at the repository root. The ``sys.path`` insert keeps the
in-place (uninstalled) layout working; an installed package works without it.
"""

from __future__ import annotations

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from rra.api import app  # noqa: E402,F401

__all__ = ["app"]
