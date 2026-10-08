"""Render the assumptions register to docs/assumptions.md.

One command keeps the document and the code in sync:
    python scripts/render_assumptions.py
"""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from rra.assumptions import AssumptionRegister  # noqa: E402


def main() -> None:
    register = AssumptionRegister.default()
    out = ROOT / "docs" / "assumptions.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(register.to_markdown(), encoding="utf-8")
    print(f"wrote {out.relative_to(ROOT)} ({len(register.names())} parameters)")


if __name__ == "__main__":
    main()
