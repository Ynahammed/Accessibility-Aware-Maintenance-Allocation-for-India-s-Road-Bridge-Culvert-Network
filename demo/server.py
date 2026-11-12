"""Local demo entry point.

Kept so the documented command and the existing tests keep working:

    python demo/server.py --port 8737

The implementation lives in ``rra.serve`` so the FastAPI app and this server share one
service layer (``rra.app``).
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from rra.serve import *  # noqa: E402,F401,F403
from rra.serve import DemoHandler, main  # noqa: E402,F401

if __name__ == "__main__":
    main()
