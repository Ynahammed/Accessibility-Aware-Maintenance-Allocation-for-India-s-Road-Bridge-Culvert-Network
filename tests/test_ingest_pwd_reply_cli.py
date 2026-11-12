"""CLI summary tests for the PWD/RTI reply loader."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from test_pwd_reply import _write_sor_crew_reply

ROOT = Path(__file__).resolve().parents[1]


def test_cli_prints_labour_overrides_and_derivation(tmp_path):
    reply = _write_sor_crew_reply(tmp_path / "reply")
    out = tmp_path / "out"
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "ingest_pwd_reply.py"),
            str(reply),
            "--out",
            str(out),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "crew-days (base minor-repair labour, days)" in result.stdout
    assert "culvert        5.50" in result.stdout
    assert "minor_bridge   17.50" in result.stdout
    assert "major_bridge   27.60" in result.stdout
    assert "major crew days 69 / LABOUR_MULTIPLIER[major]=2.5" in result.stdout
