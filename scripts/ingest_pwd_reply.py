"""Ingest a PWD/RTI reply and update the assumptions register's provenance.

    python scripts/ingest_pwd_reply.py data/raw/pwd/rti_2026_11
    python scripts/ingest_pwd_reply.py data/raw/pwd/rti_2026_11 --write-docs

Reads the reply directory described by its ``manifest.json`` (see
``docs/rti/reply_template/``), derives the quantities the register currently assumes, and
writes:

* ``<out>/register_overrides.json`` — every override with its provenance, and every
  parameter left alone with the reason;
* ``<out>/coverage.json`` — what the reply covered and what it did not;
* ``<out>/condition_transitions.csv`` — inspection-to-inspection condition change, exported
  for later fitting (not applied: that conversion needs a modelling decision);
* with ``--write-docs``, ``docs/assumptions_measured.md``.

Nothing is written when the reply lacks provenance or the samples are too small; the
command says so and exits non-zero only on a malformed reply.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Windows consoles default to cp1252, which cannot encode the rupee sign used below.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from rra.assumptions import AssumptionRegister  # noqa: E402
from rra.ingest.pwd_reply import (  # noqa: E402
    ReplyError,
    derive,
    effective_register,
    load_reply,
    write_outputs,
)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("reply_dir", type=Path, help="directory holding manifest.json and the reply tables")
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "processed" / "pwd_reply")
    ap.add_argument("--write-docs", action="store_true", help="also write docs/assumptions_measured.md")
    args = ap.parse_args()

    register = AssumptionRegister.default()
    try:
        manifest, tables = load_reply(args.reply_dir)
    except ReplyError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2

    overrides = derive(manifest, tables, register)
    effective = effective_register(register, overrides)
    written = write_outputs(overrides, effective, args.out, write_docs=args.write_docs, root=ROOT)

    print(f"reply: {manifest['office']} | {manifest['application_ref']} | {manifest['reply_date']}")
    print(f"tables read: {', '.join(sorted(tables))}\n")

    if overrides.register:
        print(f"{'parameter':38s} {'was':>8s} {'now':>9s}  {'src':6s} {'n':>3s}  provenance")
        for name, u in overrides.register.items():
            print(
                f"{name:38s} {u.previous.get('default', float('nan'))!s:>8s} "
                f"{u.value:9.4g}  {u.source:6s} {u.provenance.n:3d}  "
                f"{u.provenance.table} p.{u.provenance.page or '-'}"
            )
    else:
        print("no register parameter could be measured from this reply")

    if overrides.rates:
        print("\nschedule of rates (base minor-repair cost, Rs crore):")
        for stype, u in overrides.rates.items():
            print(f"  {stype:14s} {u.value:.4f}   n={u.provenance.n}  {u.provenance.detail}")

    labour_skips = [s for s in overrides.skipped if s["parameter"].startswith("labour_days::")]
    if overrides.labour or labour_skips:
        print("\ncrew-days (base minor-repair labour, days):")
        for stype, u in overrides.labour.items():
            print(f"  {stype:14s} {u.value:.2f}   n={u.provenance.n}  {u.provenance.detail}")
        if not overrides.labour:
            print("  no overrides applied")
        for s in labour_skips:
            extra = ", ".join(f"{k}={v}" for k, v in s.items() if k not in {"parameter", "reason"})
            print(f"  {s['parameter']:38s} {s['reason']} ({extra})")

    if overrides.skipped:
        print("\nleft as assumptions:")
        for s in overrides.skipped:
            if s["parameter"].startswith("labour_days::"):
                continue
            extra = ", ".join(f"{k}={v}" for k, v in s.items() if k not in {"parameter", "reason"})
            print(f"  {s['parameter']:38s} {s['reason']} ({extra})")

    print("\nwritten:")
    for label, path in written.items():
        print(f"  {label:10s} {path.relative_to(ROOT) if path.is_relative_to(ROOT) else path}")
    if not args.write_docs:
        print("\n(docs/assumptions_measured.md not written; pass --write-docs to render it)")
    print("\neffective register preview:")
    for name in sorted(overrides.register):
        p = effective[name]
        print(f"  {name:38s} {p.default:g}  [{p.low:g}, {p.high:g}]  {p.source}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
