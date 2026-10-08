"""Pytest bootstrap: put ``src/`` on the path so ``import rra`` works in-place.

Packaging/install is intentionally deferred; this keeps the test suite runnable today.
"""

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
